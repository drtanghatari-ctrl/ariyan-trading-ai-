"""A040 MetaTrader 5 DEMO-ONLY broker adapter (works with any MT5 broker, e.g. Opofinance).

The adapter implements the A039 `Broker` interface on top of the official
`MetaTrader5` Python module, which is injected so it can be tested without a
terminal. It refuses to operate on anything but a demo account: the account type is
verified at connect time and again before every order or close, so a terminal that
is switched to a real account is detected and refused.

Credentials are passed to `connect` once and never stored, logged or returned.
Nothing here is investment advice or evidence that a strategy works.
"""
import re
from decimal import Decimal

from .execution import (
    AccountState, Broker, BrokerMode, OrderRequest, OrderResult, OrderSide, Position, Quote,
)
from .instruments import _on_grid

_CERTAIN_REJECTIONS = (
    'TRADE_RETCODE_REJECT', 'TRADE_RETCODE_INVALID', 'TRADE_RETCODE_INVALID_VOLUME',
    'TRADE_RETCODE_INVALID_PRICE', 'TRADE_RETCODE_INVALID_STOPS', 'TRADE_RETCODE_TRADE_DISABLED',
    'TRADE_RETCODE_MARKET_CLOSED', 'TRADE_RETCODE_NO_MONEY', 'TRADE_RETCODE_PRICE_CHANGED',
    'TRADE_RETCODE_PRICE_OFF', 'TRADE_RETCODE_INVALID_FILL', 'TRADE_RETCODE_TOO_MANY_REQUESTS',
    'TRADE_RETCODE_LIMIT_VOLUME', 'TRADE_RETCODE_POSITION_CLOSED', 'TRADE_RETCODE_REQUOTE',
    'TRADE_RETCODE_LONG_ONLY', 'TRADE_RETCODE_SHORT_ONLY', 'TRADE_RETCODE_CLOSE_ONLY',
    'TRADE_RETCODE_FIFO_CLOSE', 'TRADE_RETCODE_LIMIT_ORDERS', 'TRADE_RETCODE_INVALID_EXPIRATION',
)
_SYMBOL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/#-]{0,39}')


class MT5Error(RuntimeError):
    """The terminal could not be used safely; the order outcome may be unknown."""


def load_mt5():
    """Import the official module; it only exists on Windows with a terminal installed."""
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise MT5Error('The MetaTrader5 Python package is not installed. It needs Windows and an '
                       'installed MetaTrader 5 terminal: pip install MetaTrader5') from exc
    return mt5


def _dec(value):
    # Terminal numbers are doubles already rounded to the instrument's digits. Rounding to 8
    # places only strips binary float noise (1.1057700000000002) and never changes a real value.
    if isinstance(value, float):
        return Decimal(str(round(value, 8)))
    return Decimal(str(value))


class MT5DemoBroker(Broker):
    def __init__(self, mt5, magic, symbol_map=None, deviation_points=10, expected_server=None):
        if type(magic) is not int or not 0 < magic < 2**31:
            raise ValueError('magic must be a positive 31-bit integer identifying this system')
        if type(deviation_points) is not int or not 0 <= deviation_points <= 1000:
            raise ValueError('deviation_points must be an integer 0..1000')
        symbol_map = dict(symbol_map or {})
        if any(type(k) is not str or type(v) is not str or not _SYMBOL.fullmatch(v)
               for k, v in symbol_map.items()):
            raise ValueError('symbol_map must map canonical symbols to broker symbols')
        if expected_server is not None and (type(expected_server) is not str or not expected_server):
            raise ValueError('expected_server must be a non-empty string or None')
        self._mt5, self._magic, self._deviation = mt5, magic, deviation_points
        self._to_broker = symbol_map
        self._from_broker = {v: k for k, v in symbol_map.items()}
        self._expected_server = expected_server
        self._connected, self._currency, self._results = False, None, {}
        self._margin_mode = None

    # ----- connection
    @property
    def mode(self):
        return BrokerMode.DEMO

    def connect(self, login, password, server, path=None):
        """Initialize the terminal, log in and verify a DEMO account. Credentials are not kept."""
        if type(login) is not int or login <= 0 or type(password) is not str or not password \
                or type(server) is not str or not server:
            raise ValueError('login (int), password and server are required')
        kwargs = {'login': login, 'password': password, 'server': server}
        if path:
            kwargs['path'] = path
        try:
            ok = self._mt5.initialize(**kwargs)
        finally:
            kwargs.clear()
            password = None
        if not ok:
            raise MT5Error('MT5 initialize failed: %r' % (self._mt5.last_error(),))
        try:
            self._verify_demo()
        except MT5Error:
            self._mt5.shutdown()
            self._connected = False
            raise
        self._connected = True

    def close(self):
        self._mt5.shutdown()
        self._connected = False

    def _verify_demo(self):
        info = self._mt5.account_info()
        if info is None:
            raise MT5Error('No account information is available from the terminal')
        if info.trade_mode != self._mt5.ACCOUNT_TRADE_MODE_DEMO:
            raise MT5Error('Refusing to operate: the account is not a DEMO account')
        if self._expected_server is not None and info.server != self._expected_server:
            raise MT5Error('Refusing to operate: unexpected server %s' % info.server)
        if not info.trade_allowed:
            raise MT5Error('Trading is disabled for this account in the terminal')
        self._currency = info.currency
        self._margin_mode = getattr(info, 'margin_mode', None)
        return info

    def account_type(self):
        """HEDGING, NETTING, EXCHANGE or UNKNOWN, as reported by the terminal."""
        mode = self._margin_mode
        for name, label in (('ACCOUNT_MARGIN_MODE_RETAIL_HEDGING', 'HEDGING'),
                            ('ACCOUNT_MARGIN_MODE_RETAIL_NETTING', 'NETTING'),
                            ('ACCOUNT_MARGIN_MODE_EXCHANGE', 'EXCHANGE')):
            if mode is not None and mode == getattr(self._mt5, name, object()):
                return label
        return 'UNKNOWN'

    def _one_position_per_symbol(self):
        # Netting and exchange accounts merge orders into one position per symbol; an unknown
        # mode is treated the same way, which is the stricter rule.
        return self.account_type() != 'HEDGING'

    def _ready(self):
        if not self._connected:
            raise MT5Error('Not connected; call connect() first')
        return self._verify_demo()  # re-checked every time: a switched terminal is refused

    # ----- read side
    def account(self):
        info = self._ready()
        return AccountState(info.currency, _dec(info.balance), _dec(info.equity), _dec(info.margin),
                            _dec(info.margin_free), BrokerMode.DEMO)

    def _canonical(self, broker_symbol):
        return self._from_broker.get(broker_symbol, broker_symbol)

    def _broker_symbol(self, symbol):
        return self._to_broker.get(symbol, symbol)

    def _ours(self):
        raw = self._mt5.positions_get()
        if raw is None:
            raise MT5Error('positions_get failed: %r' % (self._mt5.last_error(),))
        return [p for p in raw if p.magic == self._magic]

    def positions(self):
        self._ready()
        out = []
        for p in self._ours():
            side = OrderSide.BUY if p.type == self._mt5.POSITION_TYPE_BUY else OrderSide.SELL
            out.append(Position(str(p.ticket), self._canonical(p.symbol), side, _dec(p.volume),
                                _dec(p.price_open), _dec(p.sl) if p.sl else None,
                                _dec(p.tp) if p.tp else None, int(p.time_msc), _dec(p.profit)))
        return tuple(out)

    def quote(self, symbol):
        self._ready()
        broker_symbol = self._broker_symbol(symbol)
        tick = self._mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            raise MT5Error('No tick for %s: %r' % (broker_symbol, self._mt5.last_error()))
        return Quote(_dec(tick.bid), _dec(tick.ask), int(tick.time_msc))

    # ----- read-only market data (A042)
    _TIMEFRAMES = {'M1': 60, 'M5': 300, 'M15': 900, 'M30': 1800, 'H1': 3600, 'H4': 14400, 'D1': 86400}

    def timeframe_seconds(self, timeframe):
        if timeframe not in self._TIMEFRAMES:
            raise ValueError('timeframe must be one of %s' % ', '.join(self._TIMEFRAMES))
        return self._TIMEFRAMES[timeframe]

    def closed_candles(self, symbol, timeframe, count):
        """The last `count` fully CLOSED candles, oldest first (the forming bar is excluded).

        Timestamps are the broker's SERVER time written as if it were UTC (milliseconds);
        they are consistent for ordering but are not true UTC. Volume is the tick volume.
        """
        from .market_data import Candle
        self.timeframe_seconds(timeframe)
        if type(count) is not int or not 1 <= count <= 5000:
            raise ValueError('count must be an integer between 1 and 5000')
        self._ready()
        broker_symbol = self._broker_symbol(symbol)
        constant = getattr(self._mt5, 'TIMEFRAME_' + timeframe, None)
        if constant is None:
            raise MT5Error('The terminal module has no timeframe %s' % timeframe)
        rates = self._mt5.copy_rates_from_pos(broker_symbol, constant, 1, count)
        if rates is None or len(rates) == 0:
            raise MT5Error('No candles for %s %s: %r' % (broker_symbol, timeframe, self._mt5.last_error()))
        candles = []

        def price(value):
            # Terminal prices are doubles already rounded to the symbol's digits; rounding to 8
            # places only strips binary float noise and never changes a real price.
            return _dec(round(float(value), 8))

        for rate in rates:
            try:
                candles.append(Candle(int(rate['time']) * 1000, price(rate['open']), price(rate['high']),
                                      price(rate['low']), price(rate['close']), _dec(int(rate['tick_volume']))))
            except ValueError as exc:
                raise MT5Error('Unusable candle from the terminal: %s' % exc) from exc
        for earlier, later in zip(candles, candles[1:]):
            if later.timestamp_ms <= earlier.timestamp_ms:
                raise MT5Error('Terminal returned unordered candles')
        return tuple(candles)

    def symbol_terms(self, symbol):
        """Contract terms the terminal reports for a symbol, as Decimals (read-only)."""
        self._ready()
        info = self._mt5.symbol_info(self._broker_symbol(symbol))
        if info is None:
            raise MT5Error('Unknown symbol %s: %r' % (self._broker_symbol(symbol), self._mt5.last_error()))
        return {'contract_size': _dec(info.trade_contract_size), 'lot_min': _dec(info.volume_min),
                'lot_max': _dec(info.volume_max), 'lot_step': _dec(info.volume_step),
                'point': _dec(info.point), 'digits': int(info.digits)}

    # ----- trading
    def _filling(self, info):
        flags = info.filling_mode
        if flags & self._mt5.SYMBOL_FILLING_FOK:
            return self._mt5.ORDER_FILLING_FOK
        if flags & self._mt5.SYMBOL_FILLING_IOC:
            return self._mt5.ORDER_FILLING_IOC
        return self._mt5.ORDER_FILLING_RETURN

    def _certain_rejections(self):
        codes = set()
        for name in _CERTAIN_REJECTIONS:
            code = getattr(self._mt5, name, None)
            if code is not None:
                codes.add(code)
        return codes

    def _send(self, client_order_id, request, price, lots, position_id=None):
        result = self._mt5.order_send(request)
        if result is None:
            raise MT5Error('order_send returned nothing: the order outcome is UNKNOWN (%r)'
                           % (self._mt5.last_error(),))
        if result.retcode == self._mt5.TRADE_RETCODE_DONE:
            return OrderResult(client_order_id, 'FILLED', 'OK',
                               position_id or str(result.order), _dec(result.price or price),
                               _dec(result.volume or lots), None)
        if result.retcode in self._certain_rejections():
            return OrderResult(client_order_id, 'REJECTED',
                               'RETCODE_%s:%s' % (result.retcode, str(result.comment)[:60]))
        raise MT5Error('Ambiguous order_send retcode %s (%s): the outcome is UNKNOWN'
                       % (result.retcode, str(result.comment)[:60]))

    def _check_id(self, client_order_id):
        if type(client_order_id) is not str or not 1 <= len(client_order_id) <= 31 \
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:-]*', client_order_id):
            raise ValueError('MT5 comments allow client order IDs of at most 31 characters')

    def submit(self, request):
        if type(request) is not OrderRequest:
            raise ValueError('OrderRequest required')
        self._check_id(request.client_order_id)
        key = ('SUBMIT', request.symbol, request.side, request.lots, request.stop_loss, request.take_profit)
        known = self._results.get(request.client_order_id)
        if known is not None:
            return known[1] if known[0] == key else OrderResult(
                request.client_order_id, 'REJECTED', 'DUPLICATE_ID_CONFLICT')
        self._ready()
        # After a restart, an open position tagged with this ID proves the order already filled.
        for p in self._ours():
            if p.comment == request.client_order_id:
                result = OrderResult(request.client_order_id, 'FILLED', 'ALREADY_OPEN', str(p.ticket),
                                     _dec(p.price_open), _dec(p.volume), int(p.time_msc))
                self._results[request.client_order_id] = (key, result)
                return result
        broker_symbol = self._broker_symbol(request.symbol)
        reject = lambda reason: self._remember(key, OrderResult(request.client_order_id, 'REJECTED', reason))
        if self._one_position_per_symbol():
            # Any position on the symbol, ours or manual, would absorb this order instead of
            # opening a separate one. Close it first (close_position), then submit.
            raw = self._mt5.positions_get()
            if raw is None:
                raise MT5Error('positions_get failed: %r' % (self._mt5.last_error(),))
            if any(p.symbol == broker_symbol for p in raw):
                return reject('NETTING_SYMBOL_ALREADY_HAS_POSITION')
        info = self._mt5.symbol_info(broker_symbol)
        if info is None or not self._mt5.symbol_select(broker_symbol, True):
            return reject('UNKNOWN_SYMBOL')
        lot_min, lot_max, lot_step = _dec(info.volume_min), _dec(info.volume_max), _dec(info.volume_step)
        if not (lot_min <= request.lots <= lot_max and _on_grid(request.lots, lot_step)):
            return reject('LOTS_OUTSIDE_SYMBOL_TERMS')
        tick = self._mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return reject('NO_TICK')
        buy = request.side is OrderSide.BUY
        price = tick.ask if buy else tick.bid
        order = {
            'action': self._mt5.TRADE_ACTION_DEAL, 'symbol': broker_symbol,
            'volume': float(request.lots),
            'type': self._mt5.ORDER_TYPE_BUY if buy else self._mt5.ORDER_TYPE_SELL,
            'price': float(price),
            'sl': float(request.stop_loss) if request.stop_loss is not None else 0.0,
            'tp': float(request.take_profit) if request.take_profit is not None else 0.0,
            'deviation': self._deviation, 'magic': self._magic, 'comment': request.client_order_id,
            'type_time': self._mt5.ORDER_TIME_GTC, 'type_filling': self._filling(info),
        }
        result = self._send(request.client_order_id, order, price, request.lots)
        return self._remember(key, result)

    def _remember(self, key, result):
        self._results[result.client_order_id] = (key, result)
        return result

    def close_position(self, position_id, client_order_id):
        self._check_id(client_order_id)
        key = ('CLOSE', str(position_id))
        known = self._results.get(client_order_id)
        if known is not None:
            return known[1] if known[0] == key else OrderResult(
                client_order_id, 'REJECTED', 'DUPLICATE_ID_CONFLICT')
        self._ready()
        match = [p for p in self._ours() if str(p.ticket) == str(position_id)]
        if not match:
            return self._remember(key, OrderResult(client_order_id, 'REJECTED', 'UNKNOWN_POSITION'))
        p = match[0]
        info = self._mt5.symbol_info(p.symbol)
        tick = self._mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None:
            return self._remember(key, OrderResult(client_order_id, 'REJECTED', 'NO_TICK'))
        was_buy = p.type == self._mt5.POSITION_TYPE_BUY
        price = tick.bid if was_buy else tick.ask
        order = {
            'action': self._mt5.TRADE_ACTION_DEAL, 'symbol': p.symbol, 'volume': float(p.volume),
            'type': self._mt5.ORDER_TYPE_SELL if was_buy else self._mt5.ORDER_TYPE_BUY,
            'position': p.ticket, 'price': float(price), 'deviation': self._deviation,
            'magic': self._magic, 'comment': client_order_id, 'type_time': self._mt5.ORDER_TIME_GTC,
            'type_filling': self._filling(info),
        }
        result = self._send(client_order_id, order, price, p.volume, position_id=str(p.ticket))
        return self._remember(key, result)
