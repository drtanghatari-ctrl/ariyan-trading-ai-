"""A036 account-currency conversion for offline backtests.

A conversion path is a chain of legs; each leg is an ordinary price series (for
example USDJPY candles) used in either direction. Converting a quote-currency
amount to the account currency multiplies it by the product of every leg's
"account per quote" rate. Rates at fills use the leg candle's open, marks use the
close, and stop-out tests use the adverse extreme of each leg. Arithmetic runs at
50 significant digits; inversion (1/price) is the only inexact step.

Rates come from caller-supplied candles. Their provenance, and whether they match
real broker conversion, is the caller's responsibility.
"""
import re
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN

from .market_data import CandleDataset
from .session_candles import SessionCandleDataset

CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
ONE = Decimal(1)
_CODE = re.compile(r'[A-Z][A-Z0-9_.:/-]{0,23}')


@dataclass(frozen=True)
class ConversionLeg:
    """Converts `from_currency` into `to_currency` using `dataset` prices.

    inverted=False: the price is `to_currency` per 1 `from_currency` (GBPUSD for GBP->USD).
    inverted=True:  the price is `from_currency` per 1 `to_currency` (USDJPY for JPY->USD).
    """
    dataset: object
    from_currency: str
    to_currency: str
    inverted: bool

    def __post_init__(self):
        if type(self.dataset) not in (CandleDataset, SessionCandleDataset):
            raise ValueError('A validated candle dataset is required for a conversion leg')
        for name in ('from_currency', 'to_currency'):
            value = getattr(self, name)
            if type(value) is not str or not _CODE.fullmatch(value):
                raise ValueError('Invalid ' + name)
        if self.from_currency == self.to_currency:
            raise ValueError('A conversion leg must change currency')
        if type(self.inverted) is not bool:
            raise ValueError('inverted must be a boolean')

    def describe(self):
        return {'from': self.from_currency, 'to': self.to_currency, 'inverted': self.inverted,
                'symbol': self.dataset.symbol, 'dataset_sha256': self.dataset.raw_sha256,
                'source': self.dataset.source}


@dataclass(frozen=True)
class BarRates:
    """Account-per-quote conversion rates for one bar."""
    open: Decimal
    close: Decimal
    high: Decimal   # largest rate seen in the bar
    low: Decimal    # smallest rate seen in the bar


IDENTITY = BarRates(ONE, ONE, ONE, ONE)


def validate_path(legs, quote_currency, account_currency):
    if type(legs) is not tuple:
        raise ValueError('Conversion must be a tuple of ConversionLeg objects')
    if quote_currency == account_currency:
        if legs:
            raise ValueError('No conversion legs are allowed when quote and account currency match')
        return
    if not legs:
        raise ValueError('Conversion legs are required: %s -> %s' % (quote_currency, account_currency))
    current = quote_currency
    for leg in legs:
        if type(leg) is not ConversionLeg:
            raise ValueError('Conversion must be a tuple of ConversionLeg objects')
        if leg.from_currency != current:
            raise ValueError('Conversion legs do not chain from %s' % current)
        current = leg.to_currency
    if current != account_currency:
        raise ValueError('Conversion legs end in %s, not the account currency %s' % (current, account_currency))


def _leg_rates(candle, inverted):
    if not inverted:
        return candle.open, candle.close, candle.high, candle.low
    # 1/price: the high of the converted rate comes from the low price.
    return (ONE / candle.open, ONE / candle.close, ONE / candle.low, ONE / candle.high)


def build_rates(legs, timestamps):
    """Return one BarRates per timestamp; every timestamp must exist in every leg."""
    if not legs:
        return tuple(IDENTITY for _ in timestamps)
    maps = []
    for leg in legs:
        index = {c.timestamp_ms: c for c in leg.dataset.candles}
        if leg.dataset.interval_ms is None or len(index) != len(leg.dataset.candles):
            raise ValueError('Conversion dataset has duplicate timestamps')
        maps.append((index, leg.inverted))
    rates = []
    for ts in timestamps:
        o = c = h = l = ONE
        for index, inverted in maps:
            candle = index.get(ts)
            if candle is None:
                raise ValueError('Conversion series has no candle at %d' % ts)
            lo, lc, lh, ll = _leg_rates(candle, inverted)
            o, c, h, l = o * lo, c * lc, h * lh, l * ll
        rates.append(BarRates(o, c, h, l))
    return tuple(rates)
