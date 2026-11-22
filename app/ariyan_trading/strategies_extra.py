"""A043 additional rule-based strategies built from widely documented, simple ideas.

Same contract as A034: deterministic, decision at a CLOSED candle, no access to anything but the
`history` window. Rules that need an exit memory (breakout, mean reversion) rebuild their state by
scanning the window they are given, so the result depends only on the last `lookback` candles and the
backtester, the walk-forward harness and the live runner all behave identically.

NOTHING HERE IS A CLAIM OF PROFITABILITY. These are standard textbook rules (trend following,
breakouts, short-horizon mean reversion). Published evidence is strongest for diversified time-series
momentum across many markets; a single currency pair with default parameters is a weak test, and
backtest results alone predict out-of-sample results poorly. Judge them only with walk-forward results
on data the parameters never saw, after realistic costs.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext

from .market_data import integer
from .strategies import MAX_LOOKBACK, Signal, Strategy, _history

_CTX = 50


def _bool(value, name):
    if type(value) is not bool:
        raise ValueError('%s must be a boolean' % name)


def _mean(values):
    return sum(values) / len(values)


@dataclass(frozen=True)
class TrendFilter(Strategy):
    """Close above its simple moving average -> LONG; below -> SHORT (or FLAT)."""
    window: int = 200
    allow_short: bool = False
    name = 'trend_filter'

    def __post_init__(self):
        integer(self.window, 'window', 2)
        if self.window > MAX_LOOKBACK:
            raise ValueError('window too large')
        _bool(self.allow_short, 'allow_short')

    @property
    def lookback(self):
        return self.window

    def target(self, history):
        bars = _history(history, self.window)
        with localcontext() as ctx:
            ctx.prec = _CTX
            average = _mean([c.close for c in bars])
        if bars[-1].close > average:
            return Signal.LONG
        if bars[-1].close < average:
            return Signal.SHORT if self.allow_short else Signal.FLAT
        return Signal.FLAT


@dataclass(frozen=True)
class DonchianBreakout(Strategy):
    """Turtle-style channel breakout on closes.

    Enter long when the close exceeds the highest close of the previous `entry_window` bars (short on
    the lowest). Exit when the close crosses the opposite extreme of the previous `exit_window` bars.
    """
    entry_window: int = 20
    exit_window: int = 10
    allow_short: bool = False
    warmup: int = 100
    name = 'donchian_breakout'

    def __post_init__(self):
        integer(self.entry_window, 'entry_window', 2)
        integer(self.exit_window, 'exit_window', 1)
        integer(self.warmup, 'warmup', 0)
        if self.exit_window > self.entry_window:
            raise ValueError('exit_window must not exceed entry_window')
        if self.entry_window + self.warmup > MAX_LOOKBACK:
            raise ValueError('window too large')
        _bool(self.allow_short, 'allow_short')

    @property
    def lookback(self):
        return self.entry_window + self.warmup + 1

    def target(self, history):
        bars = _history(history, self.lookback)
        closes = [c.close for c in bars]
        position = Signal.FLAT
        for i in range(self.entry_window, len(closes)):
            entry_high = max(closes[i - self.entry_window:i])
            entry_low = min(closes[i - self.entry_window:i])
            exit_high = max(closes[i - self.exit_window:i])
            exit_low = min(closes[i - self.exit_window:i])
            close = closes[i]
            if position is Signal.LONG and close < exit_low:
                position = Signal.FLAT
            elif position is Signal.SHORT and close > exit_high:
                position = Signal.FLAT
            if position is Signal.FLAT:
                if close > entry_high:
                    position = Signal.LONG
                elif close < entry_low and self.allow_short:
                    position = Signal.SHORT
        return position


def _rsi(closes, period):
    """Wilder RSI series (None until `period` changes exist). Pure Decimal, no floats."""
    out = [None] * len(closes)
    if len(closes) <= period:
        return out
    gains = [max(closes[i] - closes[i - 1], Decimal(0)) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], Decimal(0)) for i in range(1, len(closes))]
    avg_gain, avg_loss = _mean(gains[:period]), _mean(losses[:period])
    for i in range(period, len(closes)):
        if i > period:
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = Decimal(100) if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


@dataclass(frozen=True)
class RsiReversion(Strategy):
    """Short-horizon mean reversion with a trend filter (Connors-style RSI(2)).

    Long when the close is above its `trend_window` average and RSI(`rsi_period`) falls below
    `oversold`; exit when the close rises above its `exit_window` average. Shorts mirror this when
    allowed (close below the trend average and RSI above 100 - oversold).
    """
    rsi_period: int = 2
    oversold: int = 10
    exit_window: int = 5
    trend_window: int = 200
    allow_short: bool = False
    warmup: int = 50
    name = 'rsi_reversion'

    def __post_init__(self):
        integer(self.rsi_period, 'rsi_period', 2)
        integer(self.exit_window, 'exit_window', 2)
        integer(self.trend_window, 'trend_window', 2)
        integer(self.warmup, 'warmup', 0)
        integer(self.oversold, 'oversold', 1)
        if self.oversold >= 50:
            raise ValueError('oversold must be below 50')
        if self.trend_window + self.warmup > MAX_LOOKBACK:
            raise ValueError('window too large')
        _bool(self.allow_short, 'allow_short')

    @property
    def lookback(self):
        return self.trend_window + self.warmup

    def target(self, history):
        bars = _history(history, self.lookback)
        closes = [c.close for c in bars]
        with localcontext() as ctx:
            ctx.prec = _CTX
            rsi = _rsi(closes, self.rsi_period)
            position = Signal.FLAT
            for i in range(self.trend_window - 1, len(closes)):
                trend = _mean(closes[i - self.trend_window + 1:i + 1])
                exit_avg = _mean(closes[i - self.exit_window + 1:i + 1])
                close = closes[i]
                if position is Signal.LONG and close > exit_avg:
                    position = Signal.FLAT
                elif position is Signal.SHORT and close < exit_avg:
                    position = Signal.FLAT
                if position is Signal.FLAT and rsi[i] is not None:
                    if close > trend and rsi[i] < self.oversold:
                        position = Signal.LONG
                    elif self.allow_short and close < trend and rsi[i] > 100 - self.oversold:
                        position = Signal.SHORT
        return position


@dataclass(frozen=True)
class BollingerReversion(Strategy):
    """Fade closes beyond `k` standard deviations from the `window` average; exit at the average."""
    window: int = 20
    k: str = '2'
    allow_short: bool = False
    warmup: int = 50
    name = 'bollinger_reversion'

    def __post_init__(self):
        integer(self.window, 'window', 2)
        integer(self.warmup, 'warmup', 0)
        object.__setattr__(self, 'k', str(Decimal(str(self.k))))
        if Decimal(self.k) <= 0 or Decimal(self.k) > 10:
            raise ValueError('k must be in (0, 10]')
        if self.window + self.warmup > MAX_LOOKBACK:
            raise ValueError('window too large')
        _bool(self.allow_short, 'allow_short')

    @property
    def lookback(self):
        return self.window + self.warmup

    def target(self, history):
        bars = _history(history, self.lookback)
        closes = [c.close for c in bars]
        with localcontext() as ctx:
            ctx.prec = _CTX
            k = Decimal(self.k)
            position = Signal.FLAT
            for i in range(self.window - 1, len(closes)):
                chunk = closes[i - self.window + 1:i + 1]
                mean = _mean(chunk)
                spread = (sum((x - mean) ** 2 for x in chunk) / self.window).sqrt()
                close = closes[i]
                if position is Signal.LONG and close >= mean:
                    position = Signal.FLAT
                elif position is Signal.SHORT and close <= mean:
                    position = Signal.FLAT
                if position is Signal.FLAT and spread > 0:
                    if close < mean - k * spread:
                        position = Signal.LONG
                    elif self.allow_short and close > mean + k * spread:
                        position = Signal.SHORT
        return position


@dataclass(frozen=True)
class Ensemble(Strategy):
    """Combine member strategies. rule 'majority': more than half agree; 'unanimous': all agree.

    Anything else is FLAT. Averaging several different, individually weak rules is a common way to
    reduce dependence on any one parameter choice; it does not create an edge that is not there.
    """
    members: tuple = ()
    rule: str = 'majority'
    name = 'ensemble'

    def __post_init__(self):
        if type(self.members) is not tuple or len(self.members) < 2 or any(
                not isinstance(m, Strategy) for m in self.members):
            raise ValueError('members must be a tuple of at least two Strategy objects')
        if self.rule not in ('majority', 'unanimous'):
            raise ValueError("rule must be 'majority' or 'unanimous'")

    @property
    def lookback(self):
        return max(m.lookback for m in self.members)

    def params(self):
        return {'rule': self.rule, 'members': [m.describe() for m in self.members]}

    def target(self, history):
        votes = [m.target(history) for m in self.members]
        longs, shorts = votes.count(Signal.LONG), votes.count(Signal.SHORT)
        need = len(votes) if self.rule == 'unanimous' else len(votes) // 2 + 1
        if longs >= need:
            return Signal.LONG
        if shorts >= need:
            return Signal.SHORT
        return Signal.FLAT
