"""A039 broker-neutral execution interface, simulated paper broker and fail-closed guard.

Nothing here connects to a real venue. `PaperBroker` simulates fills from
caller-supplied quotes. `GuardedBroker` wraps any broker with hard risk limits and
a kill switch, and refuses a LIVE-mode broker outright: this version has no path
to real-money trading. All orders are idempotent by client order ID.
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum

from .instruments import _on_grid, _positive
from .margin_instruments import MarginInstrumentSpec
from .market_data import number
from .strategies import Signal, Strategy

CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
_TOKEN = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}')
_SYMBOL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,39}')


class OrderSide(Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class BrokerMode(Enum):
    PAPER = 'PAPER'   # simulated in this process
    DEMO = 'DEMO'     # a broker's practice account (no real money)
    LIVE = 'LIVE'     # real money: refused by GuardedBroker in this version


def _decimal(value, name):
    if value is None:
        return None
    return _positive(value, name)


@dataclass(frozen=True)
class OrderRequest:
    """A market order. `lots` and prices accept Decimal or decimal strings."""
    client_order_id: str
    symbol: str
    side: OrderSide
    lots: Decimal
    stop_loss: Decimal | None = None
    take_profit: Decimal | None = None
    comment: str = ''

    def __post_init__(self):
        if type(self.client_order_id) is not str or not _TOKEN.fullmatch(self.client_order_id):
            raise ValueError('client_order_id must be a 1..64 character token')
        if type(self.symbol) is not str or not _SYMBOL.fullmatch(self.symbol):
            raise ValueError('Invalid symbol')
        if type(self.side) is not OrderSide:
            raise ValueError('OrderSide required')
        object.__setattr__(self, 'lots', _positive(self.lots, 'lots'))
        object.__setattr__(self, 'stop_loss', _decimal(self.stop_loss, 'stop_loss'))
        object.__setattr__(self, 'take_profit', _decimal(self.take_profit, 'take_profit'))
        if type(self.comment) is not str or len(self.comment) > 64 or not self.comment.isascii():
            raise ValueError('comment must be ASCII text of at most 64 characters')
        for level in (self.stop_loss, self.take_profit):
            if level is not None and level.is_nan():
                raise ValueError('Invalid price level')


@dataclass(frozen=True)
class OrderResult:
    client_order_id: str
    status: str          # FILLED, REJECTED or UNKNOWN (outcome could not be confirmed)
    reason: str
    position_id: str | None = None
    price: Decimal | None = None
    lots: Decimal | None = None
    time_ms: int | None = None

    @property
    def filled(self):
        return self.status == 'FILLED'


@dataclass(frozen=True)
class Quote:
    bid: Decimal
    ask: Decimal
    time_ms: int


@dataclass(frozen=True)
class Position:
    position_id: str
    symbol: str
    side: OrderSide
    lots: Decimal
    entry_price: Decimal
    stop_loss: Decimal | None
    take_profit: Decimal | None
    opened_ms: int
    unrealized_pnl: Decimal   # account currency


@dataclass(frozen=True)
class AccountState:
    currency: str
    balance: Decimal
    equity: Decimal
    margin_used: Decimal
    free_margin: Decimal
    mode: BrokerMode


class Broker(ABC):
    @property
    @abstractmethod
    def mode(self):
        """BrokerMode of this connection."""

    @abstractmethod
    def account(self):
        """Current AccountState."""

    @abstractmethod
    def positions(self):
        """Tuple of open Position objects."""

    @abstractmethod
    def quote(self, symbol):
        """Latest Quote for a symbol."""

    @abstractmethod
    def submit(self, request):
        """Submit an OrderRequest; must be idempotent per client_order_id."""

    @abstractmethod
    def close_position(self, position_id, client_order_id):
        """Close one position fully; idempotent per client_order_id."""


class _Open:
    __slots__ = ('position_id', 'symbol', 'side', 'lots', 'entry', 'sl', 'tp', 'opened_ms')

    def __init__(self, position_id, symbol, side, lots, entry, sl, tp, opened_ms):
        self.position_id, self.symbol, self.side, self.lots = position_id, symbol, side, lots
        self.entry, self.sl, self.tp, self.opened_ms = entry, sl, tp, opened_ms


class PaperBroker(Broker):
    """Hedging paper account driven by caller-supplied quotes.

    Market BUYs fill at the ask and SELLs at the bid. Stop-loss and take-profit are
    checked when a quote arrives; a gap fills at the quote, which can be worse than
    the stop. Margin, commission and stop-out follow the A033 instrument terms.
    Quote-currency amounts convert with `rates` (account per quote currency).
    """

    def __init__(self, specs, opening_cash, account_currency, rates=None,
                 commission_per_lot_per_side='0'):
        if (type(specs) is not dict or not specs
                or any(type(v) is not MarginInstrumentSpec or not _SYMBOL.fullmatch(str(k))
                       for k, v in specs.items())):
            raise ValueError('specs must map symbols to MarginInstrumentSpec objects')
        self._specs = dict(specs)
        self._currency = account_currency
        if type(account_currency) is not str or not account_currency:
            raise ValueError('account_currency required')
        self._balance = _positive(opening_cash, 'opening_cash')
        self._commission = Decimal(number(commission_per_lot_per_side, 'commission', allow_zero=True))
        self._rates = {}
        for ccy, rate in (rates or {}).items():
            self._rates[ccy] = _positive(rate, 'rate')
        for symbol, spec in self._specs.items():
            if spec.quote_currency != account_currency and spec.quote_currency not in self._rates:
                raise ValueError('No conversion rate for %s -> %s' % (spec.quote_currency, account_currency))
        self._quotes, self._open, self._results, self._journal = {}, {}, {}, []
        self._next_id, self._last_ms = 1, 0

    # ----- read side
    @property
    def mode(self):
        return BrokerMode.PAPER

    def _rate(self, symbol):
        quote = self._specs[symbol].quote_currency
        return Decimal(1) if quote == self._currency else self._rates[quote]

    def _mark(self, pos):
        quote = self._quotes[pos.symbol]
        spec = self._specs[pos.symbol]
        move = quote.bid - pos.entry if pos.side is OrderSide.BUY else pos.entry - quote.ask
        return move * pos.lots * spec.contract_size * self._rate(pos.symbol)

    def _margin(self, pos, price):
        spec = self._specs[pos.symbol]
        return pos.lots * spec.contract_size * price * spec.initial_margin_rate * self._rate(pos.symbol)

    def account(self):
        with localcontext(CONTEXT):
            equity = self._balance + sum((self._mark(p) for p in self._open.values()), Decimal(0))
            used = sum((self._margin(p, p.entry) for p in self._open.values()), Decimal(0))
            return AccountState(self._currency, self._balance, equity, used, equity - used, self.mode)

    def positions(self):
        with localcontext(CONTEXT):
            return tuple(Position(p.position_id, p.symbol, p.side, p.lots, p.entry, p.sl, p.tp,
                                  p.opened_ms, self._mark(p)) for p in self._open.values())

    def quote(self, symbol):
        if symbol not in self._quotes:
            raise ValueError('No quote for %s' % symbol)
        return self._quotes[symbol]

    def journal(self):
        return tuple(dict(entry) for entry in self._journal)

    # ----- market data in
    def set_quote(self, symbol, bid, ask, time_ms):
        if symbol not in self._specs:
            raise ValueError('Unknown symbol')
        bid, ask = _positive(bid, 'bid'), _positive(ask, 'ask')
        spec = self._specs[symbol]
        if ask < bid or not (_on_grid(bid, spec.price_step) and _on_grid(ask, spec.price_step)):
            raise ValueError('Quote must satisfy ask >= bid and lie on the price grid')
        if type(time_ms) is not int or time_ms < self._last_ms:
            raise ValueError('Quote times must be integers and not move backwards')
        self._last_ms = time_ms
        self._quotes[symbol] = Quote(bid, ask, time_ms)
        with localcontext(CONTEXT):
            self._check_triggers(symbol)
            self._check_stop_out()

    def _check_triggers(self, symbol):
        quote = self._quotes[symbol]
        for pos in list(self._open.values()):
            if pos.symbol != symbol:
                continue
            if pos.side is OrderSide.BUY:
                hit_sl = pos.sl is not None and quote.bid <= pos.sl
                hit_tp = pos.tp is not None and quote.bid >= pos.tp
            else:
                hit_sl = pos.sl is not None and quote.ask >= pos.sl
                hit_tp = pos.tp is not None and quote.ask <= pos.tp
            if hit_sl or hit_tp:
                self._close(pos, 'STOP_LOSS' if hit_sl else 'TAKE_PROFIT')

    def _check_stop_out(self):
        while self._open:
            equity = self._balance + sum((self._mark(p) for p in self._open.values()), Decimal(0))
            required = Decimal(0)
            for p in self._open.values():
                quote = self._quotes[p.symbol]
                spec = self._specs[p.symbol]
                price = quote.bid if p.side is OrderSide.BUY else quote.ask
                required += (p.lots * spec.contract_size * price * spec.maintenance_margin_rate
                             * self._rate(p.symbol))
            if equity > required:
                return
            worst = min(self._open.values(), key=self._mark)
            self._close(worst, 'STOP_OUT')

    # ----- orders
    def _remember(self, request_key, result):
        self._results[result.client_order_id] = (request_key, result)
        self._journal.append({'client_order_id': result.client_order_id, 'status': result.status,
                              'reason': result.reason, 'position_id': result.position_id,
                              'price': None if result.price is None else str(result.price),
                              'lots': None if result.lots is None else str(result.lots),
                              'time_ms': result.time_ms})
        return result

    def _replay(self, request_key, client_order_id):
        known = self._results.get(client_order_id)
        if known is None:
            return None
        if known[0] != request_key:
            return OrderResult(client_order_id, 'REJECTED', 'DUPLICATE_ID_CONFLICT')
        return known[1]

    def submit(self, request):
        if type(request) is not OrderRequest:
            raise ValueError('OrderRequest required')
        key = ('SUBMIT', request.symbol, request.side, request.lots, request.stop_loss, request.take_profit)
        replay = self._replay(key, request.client_order_id)
        if replay is not None:
            return replay
        reject = lambda reason: self._remember(key, OrderResult(request.client_order_id, 'REJECTED', reason))
        spec = self._specs.get(request.symbol)
        if spec is None:
            return reject('UNKNOWN_SYMBOL')
        quote = self._quotes.get(request.symbol)
        if quote is None:
            return reject('NO_QUOTE')
        if not (spec.minimum_lot <= request.lots <= spec.maximum_lot and _on_grid(request.lots, spec.lot_step)):
            return reject('LOTS_OUTSIDE_INSTRUMENT_TERMS')
        buy = request.side is OrderSide.BUY
        price = quote.ask if buy else quote.bid
        for level, name in ((request.stop_loss, 'STOP_LOSS'), (request.take_profit, 'TAKE_PROFIT')):
            if level is not None and not _on_grid(level, spec.price_step):
                return reject(name + '_OFF_GRID')
        if request.stop_loss is not None and (request.stop_loss >= price if buy else request.stop_loss <= price):
            return reject('STOP_LOSS_ON_WRONG_SIDE')
        if request.take_profit is not None and (request.take_profit <= price if buy else request.take_profit >= price):
            return reject('TAKE_PROFIT_ON_WRONG_SIDE')
        with localcontext(CONTEXT):
            account = self.account()
            needed = (request.lots * spec.contract_size * price * spec.initial_margin_rate
                      * self._rate(request.symbol))
            commission = self._commission * request.lots
            if needed + commission > account.free_margin:
                return reject('INSUFFICIENT_MARGIN')
            self._balance -= commission
            position_id = 'P%06d' % self._next_id
            self._next_id += 1
            self._open[position_id] = _Open(position_id, request.symbol,
                                            OrderSide.BUY if buy else OrderSide.SELL, request.lots, price,
                                            request.stop_loss, request.take_profit, quote.time_ms)
        return self._remember(key, OrderResult(request.client_order_id, 'FILLED', 'OK', position_id,
                                               price, request.lots, quote.time_ms))

    def close_position(self, position_id, client_order_id):
        if type(client_order_id) is not str or not _TOKEN.fullmatch(client_order_id):
            raise ValueError('client_order_id must be a 1..64 character token')
        key = ('CLOSE', position_id)
        replay = self._replay(key, client_order_id)
        if replay is not None:
            return replay
        pos = self._open.get(position_id)
        if pos is None:
            return self._remember(key, OrderResult(client_order_id, 'REJECTED', 'UNKNOWN_POSITION'))
        with localcontext(CONTEXT):
            result = self._close(pos, 'CLOSE_REQUEST', client_order_id)
        return self._remember(key, result)

    def _close(self, pos, reason, client_order_id=None):
        quote = self._quotes[pos.symbol]
        price = quote.bid if pos.side is OrderSide.BUY else quote.ask
        spec = self._specs[pos.symbol]
        move = price - pos.entry if pos.side is OrderSide.BUY else pos.entry - price
        self._balance += move * pos.lots * spec.contract_size * self._rate(pos.symbol)
        self._balance -= self._commission * pos.lots
        del self._open[pos.position_id]
        result = OrderResult(client_order_id or 'SYSTEM-' + pos.position_id, 'FILLED', reason,
                             pos.position_id, price, pos.lots, quote.time_ms)
        if client_order_id is None:
            self._journal.append({'client_order_id': result.client_order_id, 'status': 'FILLED',
                                  'reason': reason, 'position_id': pos.position_id,
                                  'price': str(price), 'lots': str(pos.lots), 'time_ms': quote.time_ms})
        return result


@dataclass(frozen=True)
class RiskLimits:
    allowed_symbols: frozenset
    max_lots_per_order: Decimal
    max_open_positions: int
    max_total_lots: Decimal
    max_margin_fraction: Decimal      # margin used after the order / equity
    max_daily_loss_fraction: Decimal  # equity drawdown from the day's baseline that halts trading
    require_stop_loss: bool = True

    def __post_init__(self):
        if type(self.allowed_symbols) is not frozenset or not self.allowed_symbols:
            raise ValueError('allowed_symbols must be a non-empty frozenset')
        for name in ('max_lots_per_order', 'max_total_lots', 'max_margin_fraction', 'max_daily_loss_fraction'):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if not Decimal(0) < self.max_margin_fraction <= 1 or not Decimal(0) < self.max_daily_loss_fraction <= 1:
            raise ValueError('Fractions must be in (0, 1]')
        if type(self.max_open_positions) is not int or self.max_open_positions < 1:
            raise ValueError('max_open_positions must be a positive integer')
        if type(self.require_stop_loss) is not bool:
            raise ValueError('require_stop_loss must be a boolean')


class GuardedBroker(Broker):
    """Hard risk limits, daily-loss halt and kill switch in front of any broker.

    Fails closed: unknown order outcomes halt trading, a LIVE broker is refused, and
    closing positions is always allowed so risk can be reduced even when halted.
    """

    def __init__(self, broker, limits):
        if not isinstance(broker, Broker) or type(limits) is not RiskLimits:
            raise ValueError('Broker and RiskLimits required')
        self._check_mode(broker)
        self._broker, self._limits = broker, limits
        self._halted, self._halt_reason = False, ''
        self._baseline = broker.account().equity
        self._cache = {}

    @staticmethod
    def _check_mode(broker):
        if broker.mode is BrokerMode.LIVE or type(broker.mode) is not BrokerMode:
            raise ValueError('Live trading is not supported in this version; use PAPER or DEMO')

    @property
    def mode(self):
        return self._broker.mode

    @property
    def halted(self):
        return self._halted

    @property
    def halt_reason(self):
        return self._halt_reason

    def halt(self, reason='MANUAL_KILL_SWITCH'):
        self._halted, self._halt_reason = True, reason

    def start_new_day(self):
        """Reset the daily-loss baseline to current equity (does not clear a halt)."""
        self._baseline = self._broker.account().equity

    def resume(self):
        """Explicit human action: clear a halt and reset the baseline."""
        self._halted, self._halt_reason = False, ''
        self.start_new_day()

    def account(self):
        return self._broker.account()

    def positions(self):
        return self._broker.positions()

    def quote(self, symbol):
        return self._broker.quote(symbol)

    def _reject(self, request, reason):
        result = OrderResult(request.client_order_id, 'REJECTED', reason)
        self._cache[request.client_order_id] = (request, result)
        return result

    def submit(self, request):
        if type(request) is not OrderRequest:
            raise ValueError('OrderRequest required')
        known = self._cache.get(request.client_order_id)
        if known is not None:
            return known[1] if known[0] == request else OrderResult(
                request.client_order_id, 'REJECTED', 'DUPLICATE_ID_CONFLICT')
        try:
            self._check_mode(self._broker)
        except ValueError:
            self.halt('LIVE_MODE_DETECTED')
        limits = self._limits
        if self._halted:
            return self._reject(request, 'HALTED:' + self._halt_reason)
        if request.symbol not in limits.allowed_symbols:
            return self._reject(request, 'SYMBOL_NOT_ALLOWED')
        if limits.require_stop_loss and request.stop_loss is None:
            return self._reject(request, 'STOP_LOSS_REQUIRED')
        if request.lots > limits.max_lots_per_order:
            return self._reject(request, 'LOTS_ABOVE_ORDER_LIMIT')
        try:
            account = self._broker.account()
            positions = self._broker.positions()
        except Exception:
            self.halt('BROKER_STATE_UNAVAILABLE')
            return self._reject(request, 'HALTED:BROKER_STATE_UNAVAILABLE')
        if account.equity <= self._baseline * (1 - limits.max_daily_loss_fraction):
            self.halt('DAILY_LOSS_LIMIT')
            return self._reject(request, 'HALTED:DAILY_LOSS_LIMIT')
        if len(positions) >= limits.max_open_positions:
            return self._reject(request, 'TOO_MANY_POSITIONS')
        if sum((p.lots for p in positions), Decimal(0)) + request.lots > limits.max_total_lots:
            return self._reject(request, 'TOTAL_LOTS_ABOVE_LIMIT')
        if account.equity <= 0:
            return self._reject(request, 'NO_EQUITY')
        try:
            result = self._broker.submit(request)
        except Exception:
            # The order may or may not have reached the venue: stop and require a human check.
            self.halt('UNKNOWN_ORDER_OUTCOME')
            result = OrderResult(request.client_order_id, 'UNKNOWN', 'BROKER_ERROR_OUTCOME_UNKNOWN')
            self._cache[request.client_order_id] = (request, result)
            return result
        if result.filled:
            used = self._broker.account()
            if used.equity <= 0 or used.margin_used / used.equity > limits.max_margin_fraction:
                self._cache[request.client_order_id] = (request, result)
                try:
                    self._broker.close_position(result.position_id, 'UNDO-' + request.client_order_id[:55])
                except Exception:
                    self.halt('MARGIN_LIMIT_UNDO_FAILED')
                    return OrderResult(request.client_order_id, 'UNKNOWN', 'MARGIN_LIMIT_UNDO_FAILED')
                self._cache[request.client_order_id] = (request, OrderResult(
                    request.client_order_id, 'REJECTED', 'MARGIN_FRACTION_ABOVE_LIMIT_UNDONE'))
                return self._cache[request.client_order_id][1]
        self._cache[request.client_order_id] = (request, result)
        return result

    def close_position(self, position_id, client_order_id):
        return self._broker.close_position(position_id, client_order_id)

    def flatten(self, prefix='FLAT'):
        """Close every open position; allowed in any state."""
        results = []
        for index, pos in enumerate(self._broker.positions()):
            results.append(self._broker.close_position(
                pos.position_id, '%s-%s-%d' % (prefix, pos.position_id, index)))
        return tuple(results)


class SignalExecutor:
    """Turns a Strategy's target position into guarded orders, one symbol, fixed lots.

    Call `on_candle` after each fully closed candle, once the broker holds the quote
    to trade at. Orders carry deterministic IDs so a repeated call after a crash
    cannot double-submit.
    """

    def __init__(self, broker, strategy, symbol, lots, run_id, stop_distance=None):
        if not isinstance(broker, Broker) or not isinstance(strategy, Strategy):
            raise ValueError('Broker and Strategy required')
        if type(run_id) is not str or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,24}', run_id):
            raise ValueError('run_id must be a short token')
        self._broker, self._strategy, self._symbol = broker, strategy, symbol
        self._lots = _positive(lots, 'lots')
        self._distance = None if stop_distance is None else _positive(stop_distance, 'stop_distance')
        self._run, self._history, self._seq = run_id, (), 0
        self.log = []

    def warm_up(self, candles):
        """Load already-closed candles as history WITHOUT acting on them."""
        self._history = (self._history + tuple(candles))[-self._strategy.lookback:]

    def on_candle(self, candle):
        keep = self._strategy.lookback
        self._history = (self._history + (candle,))[-keep:]
        if len(self._history) < keep:
            return None
        target = self._strategy.target(self._history)
        if type(target) is not Signal:
            raise ValueError('Strategy must return a Signal')
        held = [p for p in self._broker.positions() if p.symbol == self._symbol]
        wanted = None if target is Signal.FLAT else (OrderSide.BUY if target is Signal.LONG else OrderSide.SELL)
        if len(held) == 1 and held[0].side is wanted:
            return None
        if len(held) > 1:
            raise RuntimeError('More than one position is open for %s; reconcile manually' % self._symbol)
        actions = []
        for pos in held:
            self._seq += 1
            actions.append(self._broker.close_position(pos.position_id, '%s-C%06d' % (self._run, self._seq)))
        if wanted is not None:
            self._seq += 1
            quote = self._broker.quote(self._symbol)
            price = quote.ask if wanted is OrderSide.BUY else quote.bid
            stop = None
            if self._distance is not None:
                stop = price - self._distance if wanted is OrderSide.BUY else price + self._distance
            actions.append(self._broker.submit(OrderRequest(
                '%s-O%06d' % (self._run, self._seq), self._symbol, wanted, self._lots, stop_loss=stop)))
        self.log.extend(actions)
        return tuple(actions)
