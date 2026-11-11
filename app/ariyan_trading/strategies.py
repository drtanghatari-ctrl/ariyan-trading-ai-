"""A034 stateless offline strategy interface; research use only, no trading authority.

A strategy sees only a tuple of fully closed candles ending at the decision bar
and returns the position it wants for the next bar. It cannot see future bars,
account state or the broker. Sample strategies are test fixtures, not a claimed
trading advantage.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, fields
from enum import Enum

from .market_data import Candle, integer

MAX_LOOKBACK = 10_000


class Signal(Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'
    FLAT = 'FLAT'


class Strategy(ABC):
    """Deterministic, stateless rule: closed-candle history in, target position out."""

    name = 'strategy'

    @property
    @abstractmethod
    def lookback(self):
        """Number of closed candles required before target() may be called."""

    @abstractmethod
    def target(self, history):
        """Return a Signal using only `history` (oldest first, newest = decision bar)."""

    def params(self):
        return {f.name: str(getattr(self, f.name)) for f in fields(self)} if hasattr(
            self, '__dataclass_fields__') else {}

    def describe(self):
        return {'name': self.name, 'params': self.params()}


def _history(history, minimum):
    if type(history) is not tuple or len(history) < minimum:
        raise ValueError('History must be a tuple with at least %d candles' % minimum)
    for candle in history[-minimum:]:
        if type(candle) is not Candle:
            raise ValueError('History must contain Candle objects')
    return history[-minimum:]


@dataclass(frozen=True)
class BuyAndHold(Strategy):
    """Benchmark: always long once one candle exists."""
    name = 'buy_and_hold'

    def __post_init__(self):
        pass

    @property
    def lookback(self):
        return 1

    def target(self, history):
        _history(history, 1)
        return Signal.LONG


@dataclass(frozen=True)
class SmaCross(Strategy):
    """Fast SMA above slow SMA -> LONG; below -> SHORT (or FLAT); equal -> FLAT."""
    short_window: int = 10
    long_window: int = 30
    allow_short: bool = True
    name = 'sma_cross'

    def __post_init__(self):
        integer(self.short_window, 'short_window', 1)
        integer(self.long_window, 'long_window', 2)
        if not self.short_window < self.long_window <= MAX_LOOKBACK:
            raise ValueError('Require short_window < long_window <= %d' % MAX_LOOKBACK)
        if type(self.allow_short) is not bool:
            raise ValueError('allow_short must be a boolean')

    @property
    def lookback(self):
        return self.long_window

    def target(self, history):
        window = _history(history, self.long_window)
        long_sum = sum(c.close for c in window)
        short_sum = sum(c.close for c in window[-self.short_window:])
        # Cross-multiplied comparison avoids division and rounding entirely.
        left, right = short_sum * self.long_window, long_sum * self.short_window
        if left > right:
            return Signal.LONG
        if left < right:
            return Signal.SHORT if self.allow_short else Signal.FLAT
        return Signal.FLAT


@dataclass(frozen=True)
class Momentum(Strategy):
    """Close above the close `bars` ago -> LONG; below -> SHORT (or FLAT); equal -> FLAT."""
    bars: int = 20
    allow_short: bool = True
    name = 'momentum'

    def __post_init__(self):
        integer(self.bars, 'bars', 1)
        if self.bars >= MAX_LOOKBACK:
            raise ValueError('bars must be below %d' % MAX_LOOKBACK)
        if type(self.allow_short) is not bool:
            raise ValueError('allow_short must be a boolean')

    @property
    def lookback(self):
        return self.bars + 1

    def target(self, history):
        window = _history(history, self.bars + 1)
        if window[-1].close > window[0].close:
            return Signal.LONG
        if window[-1].close < window[0].close:
            return Signal.SHORT if self.allow_short else Signal.FLAT
        return Signal.FLAT
