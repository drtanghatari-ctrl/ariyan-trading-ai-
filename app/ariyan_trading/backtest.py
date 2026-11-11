"""A035 deterministic margin-aware offline backtest; research use only.

One instrument, one position at a time, long or short. A decision made from a
fully closed bar fills at the NEXT bar's open. All money is in the instrument's
quote currency, which this module treats as the account currency (no
conversion). No broker, ledger, authorization or live trading is involved, and
results are descriptive history, not evidence of profitability or approval.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from fractions import Fraction

from .ledger_validation import bounded_decimal
from .margin_instruments import MarginInstrumentSpec, Side
from .market_data import CandleDataset, MAX_VALUE, number
from .strategies import Signal, Strategy, MAX_LOOKBACK

VERSION = 'ARIYAN-A035-BACKTEST-V1'
CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
SIX = Decimal('0.000001')
HUNDRED = Decimal(100)
MS_PER_YEAR = 31_557_600_000


@dataclass(frozen=True)
class BacktestConfig:
    opening_cash: str = '10000'
    margin_fraction: str = '0.05'
    spread: str = '0'
    commission_per_lot_per_side: str = '0'
    financing_long_per_lot_per_bar: str = '0'
    financing_short_per_lot_per_bar: str = '0'
    liquidate_at_end: bool = True
    periods_per_year: int | None = None

    def __post_init__(self):
        with localcontext(CONTEXT):
            if number(self.opening_cash, 'opening_cash') > MAX_VALUE:
                raise ValueError('opening_cash outside range')
            if not 0 < number(self.margin_fraction, 'margin_fraction') <= 1:
                raise ValueError('margin_fraction must be in (0, 1]')
            number(self.spread, 'spread', allow_zero=True)
            number(self.commission_per_lot_per_side, 'commission_per_lot_per_side', allow_zero=True)
            for name in ('financing_long_per_lot_per_bar', 'financing_short_per_lot_per_bar'):
                bounded_decimal(getattr(self, name))  # signed: positive debits, negative credits
        if type(self.liquidate_at_end) is not bool:
            raise ValueError('liquidate_at_end must be a boolean')
        if self.periods_per_year is not None and (
                type(self.periods_per_year) is not int or not 1 <= self.periods_per_year <= 10_000_000):
            raise ValueError('periods_per_year must be a positive integer or None')


@dataclass(frozen=True)
class Trade:
    side: Side
    open_ms: int
    close_ms: int
    lots: Decimal
    entry_price: Decimal
    exit_price: Decimal
    gross_pnl: Decimal
    commission: Decimal
    financing: Decimal
    net_pnl: Decimal
    reason: str

    def to_record(self):
        return {'side': self.side.value, 'open_ms': self.open_ms, 'close_ms': self.close_ms,
                'lots': _text(self.lots), 'entry_price': _text(self.entry_price),
                'exit_price': _text(self.exit_price), 'gross_pnl': _text(self.gross_pnl),
                'commission': _text(self.commission), 'financing': _text(self.financing),
                'net_pnl': _text(self.net_pnl), 'reason': self.reason}


@dataclass(frozen=True)
class BacktestResult:
    provenance: dict
    metrics: dict
    trades: tuple
    equity_curve: tuple

    def to_record(self, include_curve=False):
        record = {'version': VERSION, 'investment_evidence': False,
                  'executable_support_established': False,
                  'provenance': self.provenance, 'metrics': self.metrics,
                  'trades': [t.to_record() for t in self.trades]}
        if include_curve:
            record['equity_curve'] = [[ts, _text(eq)] for ts, eq in self.equity_curve]
        return record


def _text(value):
    return str(value.quantize(SIX))


def _floor_to_step(value, step):
    steps = (Fraction(value) / Fraction(step)).__floor__()
    return step * steps if steps > 0 else Decimal(0)


class _Position:
    __slots__ = ('side', 'lots', 'entry', 'open_ms', 'commission', 'financing')

    def __init__(self, side, lots, entry, open_ms, commission):
        self.side, self.lots, self.entry = side, lots, entry
        self.open_ms, self.commission, self.financing = open_ms, commission, Decimal(0)


class _Engine:
    def __init__(self, spec, config):
        self.spec = spec
        self.cs = spec.contract_size
        self.half = Decimal(config.spread) / 2
        self.commission = Decimal(config.commission_per_lot_per_side)
        self.fin = {Side.LONG: Decimal(config.financing_long_per_lot_per_bar),
                    Side.SHORT: Decimal(config.financing_short_per_lot_per_bar)}
        self.margin_fraction = Decimal(config.margin_fraction)
        self.balance = Decimal(config.opening_cash)
        self.position = None
        self.trades = []
        self.costs = {'spread': Decimal(0), 'commission': Decimal(0), 'financing': Decimal(0)}
        self.counts = {'stop_outs': 0, 'skipped_below_min_lot': 0, 'skipped_margin': 0,
                       'skipped_bad_price': 0, 'short_signals_ignored': 0, 'bars_in_position': 0}

    def pnl(self, side, entry, exit_, lots):
        move = exit_ - entry if side is Side.LONG else entry - exit_
        return move * lots * self.cs

    def close(self, fill, timestamp_ms, reason):
        p = self.position
        gross = self.pnl(p.side, p.entry, fill, p.lots)
        commission = self.commission * p.lots
        self.balance += gross - commission
        self.costs['commission'] += commission
        self.costs['spread'] += self.half * p.lots * self.cs
        total_commission = p.commission + commission
        self.trades.append(Trade(p.side, p.open_ms, timestamp_ms, p.lots, p.entry, fill, gross,
                                 total_commission, p.financing,
                                 gross - total_commission - p.financing, reason))
        self.position = None

    def open(self, side, price, timestamp_ms):
        fill = price + self.half if side is Side.LONG else price - self.half
        if fill <= 0:
            self.counts['skipped_bad_price'] += 1
            return
        per_lot_margin = fill * self.cs * self.spec.initial_margin_rate
        lots = _floor_to_step(self.balance * self.margin_fraction / per_lot_margin, self.spec.lot_step)
        lots = min(lots, self.spec.maximum_lot)
        if lots < self.spec.minimum_lot:
            self.counts['skipped_below_min_lot'] += 1
            return
        commission = self.commission * lots
        if lots * per_lot_margin + commission > self.balance:
            self.counts['skipped_margin'] += 1
            return
        self.balance -= commission
        self.costs['commission'] += commission
        self.costs['spread'] += self.half * lots * self.cs
        self.position = _Position(side, lots, fill, timestamp_ms, commission)

    def rebalance(self, bar, target):
        current = self.position.side if self.position else None
        wanted = None if target is Signal.FLAT else Side(target.value)
        if current is wanted:
            return
        if current is not None:
            fill = bar.open - self.half if current is Side.LONG else bar.open + self.half
            self.close(fill, bar.timestamp_ms, 'SIGNAL')
        if wanted is not None:
            self.open(wanted, bar.open, bar.timestamp_ms)

    def stop_out(self, bar):
        """Test the bar's adverse extreme against maintenance margin; liquidate there."""
        p = self.position
        worst = bar.low - self.half if p.side is Side.LONG else bar.high + self.half
        equity = self.balance + self.pnl(p.side, p.entry, worst, p.lots)
        if equity <= p.lots * self.cs * worst * self.spec.maintenance_margin_rate:
            side = p.side
            self.close(worst, bar.timestamp_ms, 'STOP_OUT')
            self.counts['stop_outs'] += 1
            return side
        return None

    def charge_financing(self):
        p = self.position
        charge = self.fin[p.side] * p.lots
        self.balance -= charge
        p.financing += charge
        self.costs['financing'] += charge
        self.counts['bars_in_position'] += 1

    def mark_price(self, bar):
        p = self.position
        return bar.close - self.half if p.side is Side.LONG else bar.close + self.half

    def equity(self, bar):
        if self.position is None:
            return self.balance
        p = self.position
        return self.balance + self.pnl(p.side, p.entry, self.mark_price(bar), p.lots)


def run_backtest(dataset, spec, strategy, config=None):
    """Replay closed bars; decisions at a close fill at the next open.

    The caller asserts the dataset and spec describe the same instrument; only
    the spec's effective interval is checked against the data range.
    """
    if type(dataset) is not CandleDataset:
        raise ValueError('A validated CandleDataset is required')
    if type(spec) is not MarginInstrumentSpec:
        raise ValueError('A MarginInstrumentSpec is required')
    if not isinstance(strategy, Strategy):
        raise ValueError('A Strategy is required')
    lookback = strategy.lookback
    if type(lookback) is not int or not 1 <= lookback <= MAX_LOOKBACK:
        raise ValueError('Invalid strategy lookback')
    config = BacktestConfig() if config is None else config
    if type(config) is not BacktestConfig:
        raise ValueError('A BacktestConfig is required')
    candles = dataset.candles
    if len(candles) <= lookback:
        raise ValueError('Dataset is too short for the strategy lookback')
    if not (spec.effective_at(candles[0].timestamp_ms) and spec.effective_at(candles[-1].timestamp_ms)):
        raise ValueError('Instrument spec is not effective across the dataset range')
    with localcontext(CONTEXT):
        return _run(dataset, spec, strategy, config, lookback)


def _run(dataset, spec, strategy, config, lookback):
    candles = dataset.candles
    engine = _Engine(spec, config)
    opening = engine.balance
    curve = []
    target = Signal.FLAT
    blocked = None
    ruined = False
    last = len(candles) - 1
    for i, bar in enumerate(candles):
        if i > 0:
            engine.rebalance(bar, target)
        if engine.position is not None:
            stopped = engine.stop_out(bar)
            if stopped is not None:
                blocked = stopped
                if engine.balance <= 0:
                    ruined = True
        if engine.position is not None:
            engine.charge_financing()
        curve.append((bar.timestamp_ms, engine.equity(bar)))
        if ruined:
            break
        if i + 1 >= lookback and i < last:
            raw = strategy.target(tuple(candles[i + 1 - lookback:i + 1]))
            if type(raw) is not Signal:
                raise ValueError('Strategy must return a Signal')
            if raw is Signal.SHORT and not spec.allows_short:
                engine.counts['short_signals_ignored'] += 1
                raw = Signal.FLAT
            if blocked is not None:
                if raw is Signal(blocked.value):
                    raw = Signal.FLAT
                else:
                    blocked = None
            target = raw
    if engine.position is not None and config.liquidate_at_end:
        bar = candles[min(len(curve) - 1, last)]
        engine.close(engine.mark_price(bar), bar.timestamp_ms, 'END')
        curve[-1] = (bar.timestamp_ms, engine.balance)
    metrics = _metrics(engine, opening, curve, config, dataset, ruined)
    provenance = {
        'dataset_symbol': dataset.symbol, 'dataset_sha256': dataset.raw_sha256,
        'dataset_source': dataset.source, 'interval_ms': dataset.interval_ms,
        'as_of_ms': dataset.as_of_ms, 'bars': len(candles), 'first_ms': candles[0].timestamp_ms,
        'last_ms': candles[-1].timestamp_ms, 'instrument_fingerprint': spec.fingerprint(),
        'strategy': strategy.describe(),
        'config': {'opening_cash': config.opening_cash, 'margin_fraction': config.margin_fraction,
                   'spread': config.spread,
                   'commission_per_lot_per_side': config.commission_per_lot_per_side,
                   'financing_long_per_lot_per_bar': config.financing_long_per_lot_per_bar,
                   'financing_short_per_lot_per_bar': config.financing_short_per_lot_per_bar,
                   'liquidate_at_end': config.liquidate_at_end,
                   'periods_per_year': config.periods_per_year},
        'currency_note': 'All amounts are in the quote currency, treated as the account currency.'}
    return BacktestResult(provenance, metrics, tuple(engine.trades), tuple(curve))


def _metrics(engine, opening, curve, config, dataset, ruined):
    final = curve[-1][1]
    peak, max_drawdown = opening, Decimal(0)
    returns, previous = [], opening
    for _, equity in curve:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak)
        returns.append(equity / previous - 1 if previous > 0 else Decimal(0))
        previous = equity
    trades = engine.trades
    wins = [t.net_pnl for t in trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in trades if t.net_pnl < 0]
    sharpe = annualized = None
    if len(returns) >= 2:
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        if variance > 0:
            sharpe = mean / variance.sqrt()
            periods = config.periods_per_year
            if periods is not None:
                annualized = sharpe * Decimal(periods).sqrt()
    bars = len(curve)

    def opt(value):
        return None if value is None else _text(value)

    return {
        'opening_equity': _text(opening), 'final_equity': _text(final),
        'total_return_pct': _text((final / opening - 1) * HUNDRED),
        'max_drawdown_pct': _text(max_drawdown * HUNDRED),
        'trades': len(trades), 'winning_trades': len(wins), 'losing_trades': len(losses),
        'win_rate_pct': opt(Decimal(len(wins)) / len(trades) * HUNDRED if trades else None),
        'profit_factor': opt(sum(wins) / -sum(losses) if losses else None),
        'average_trade_pnl': opt(sum((t.net_pnl for t in trades), Decimal(0)) / len(trades) if trades else None),
        'sharpe_per_bar': opt(sharpe), 'sharpe_annualized': opt(annualized),
        'exposure_pct': _text(Decimal(engine.counts['bars_in_position']) / bars * HUNDRED),
        'spread_cost': _text(engine.costs['spread']),
        'commission_cost': _text(engine.costs['commission']),
        'financing_cost': _text(engine.costs['financing']),
        'ruined': ruined, 'bars_simulated': bars,
        'stop_outs': engine.counts['stop_outs'],
        'skipped_below_min_lot': engine.counts['skipped_below_min_lot'],
        'skipped_margin': engine.counts['skipped_margin'],
        'skipped_bad_price': engine.counts['skipped_bad_price'],
        'short_signals_ignored': engine.counts['short_signals_ignored'],
    }
