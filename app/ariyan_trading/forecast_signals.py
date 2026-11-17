"""A046 forecast-driven signals. Offline, deterministic; research use only, no trading authority.

Forecasting models (Kronos, TimesFM, anything else) run OUTSIDE this code, on the user's machine, and write a
forecast CSV. This module reads that file, checks it, turns it into a stateless Strategy that goes through the
same backtester, costs and risk gate as every other strategy, and measures forecast quality against the
realised prices (direction, rank correlation, error against a zero forecast, interval coverage).

Forecast CSV, one row per decision bar (a forecast made at the CLOSE of that bar):
  decision_ts_ms,symbol,horizon_bars,last_close,q10,q50,q90,model,model_version,context_end_ms
q10/q50/q90 are forecast PRICES `horizon_bars` bars ahead. context_end_ms must equal decision_ts_ms: the model
may not have seen anything later. last_close is the close the model saw; if the dataset's close at that bar
differs, the signal fails closed (FLAT).

Caveat that no code here can remove: foundation models are pretrained on years of market data that very likely
include our history, so a backtest of them is optimistic by construction. Forward paper trading is the real test.
"""
import csv
import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import Path

from .strategies import Signal, Strategy, _history

MAX_ROWS = 200_000
MAX_BYTES = 32 * 1024 * 1024
HEADER = ('decision_ts_ms', 'symbol', 'horizon_bars', 'last_close', 'q10', 'q50', 'q90', 'model', 'model_version',
          'context_end_ms')
Z80 = 2.5631031311  # q90 - q10 of a standard normal


class ForecastError(ValueError):
    pass


def _price(text, name):
    try:
        value = float(text)
    except (TypeError, ValueError):
        raise ForecastError('%s is not a number' % name)
    if not math.isfinite(value) or value <= 0:
        raise ForecastError('%s must be a positive finite number' % name)
    return value


def _integer(text, name, minimum):
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ForecastError('%s is not an integer' % name)
    if value < minimum or str(value) != str(text).strip():
        raise ForecastError('%s must be an integer >= %d' % (name, minimum))
    return value


class ForecastBook:
    """Validated, immutable set of forecasts keyed by (symbol, model, horizon, decision time)."""

    def __init__(self, rows, sha256):
        self._rows = {}
        for row in rows:
            key = (row['symbol'], row['model'], row['horizon_bars'], row['decision_ts_ms'])
            if key in self._rows:
                raise ForecastError('Duplicate forecast for %r' % (key,))
            self._rows[key] = row
        self.sha256 = sha256

    def __len__(self):
        return len(self._rows)

    def __repr__(self):
        return 'ForecastBook(%d rows, sha256=%s)' % (len(self._rows), self.sha256[:12])

    def lookup(self, symbol, model, horizon_bars, decision_ts_ms):
        return self._rows.get((symbol, model, horizon_bars, decision_ts_ms))

    def rows(self, symbol, model, horizon_bars):
        return sorted((r for k, r in self._rows.items() if k[:3] == (symbol, model, horizon_bars)),
                      key=lambda r: r['decision_ts_ms'])


def parse_forecasts(raw):
    if len(raw) > MAX_BYTES:
        raise ForecastError('Forecast file exceeds the 32 MiB limit')
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    if tuple(reader.fieldnames or ()) != HEADER:
        raise ForecastError('Header must be exactly: %s' % ','.join(HEADER))
    rows = []
    for number, record in enumerate(reader, 2):
        if number - 1 > MAX_ROWS:
            raise ForecastError('Too many rows')
        try:
            row = {'decision_ts_ms': _integer(record['decision_ts_ms'], 'decision_ts_ms', 0),
                   'symbol': record['symbol'].strip(), 'horizon_bars': _integer(record['horizon_bars'], 'horizon_bars', 1),
                   'last_close': _price(record['last_close'], 'last_close'),
                   'q10': _price(record['q10'], 'q10'), 'q50': _price(record['q50'], 'q50'),
                   'q90': _price(record['q90'], 'q90'), 'model': record['model'].strip(),
                   'model_version': record['model_version'].strip(),
                   'context_end_ms': _integer(record['context_end_ms'], 'context_end_ms', 0)}
        except ForecastError as error:
            raise ForecastError('Row %d: %s' % (number, error))
        if not row['symbol'] or not row['model']:
            raise ForecastError('Row %d: symbol and model are required' % number)
        if not row['q10'] <= row['q50'] <= row['q90']:
            raise ForecastError('Row %d: quantiles must satisfy q10 <= q50 <= q90' % number)
        if row['context_end_ms'] != row['decision_ts_ms']:
            raise ForecastError('Row %d: context_end_ms must equal decision_ts_ms (no look-ahead)' % number)
        rows.append(row)
    if not rows:
        raise ForecastError('No forecasts in file')
    return rows


def load_forecasts(path):
    raw = Path(path).read_bytes()
    return ForecastBook(parse_forecasts(raw), hashlib.sha256(raw).hexdigest())


def naive_forecast(closes, window=60):
    """Baseline needing no model: median = last close, interval from trailing daily volatility."""
    if len(closes) < window + 1:
        raise ForecastError('Need at least %d closes' % (window + 1))
    tail = [float(c) for c in closes[-(window + 1):]]
    returns = [math.log(b / a) for a, b in zip(tail, tail[1:])]
    mean = sum(returns) / window
    sigma = math.sqrt(sum((r - mean) ** 2 for r in returns) / (window - 1))
    last = tail[-1]
    half = Z80 / 2 * sigma
    return last * math.exp(-half), last, last * math.exp(half)


@dataclass(frozen=True)
class ForecastSignal(Strategy):
    """LONG/SHORT only when the forecast edge beats round-trip cost plus a multiple of forecast noise.

    edge = ln(q50 / close); noise = ln(q90 / q10) / 2.563 (a one-sigma estimate); trade when
    |edge| > cost_fraction + noise_margin * noise. A missing, mismatched or stale forecast means FLAT.
    """
    book: ForecastBook
    symbol: str
    model: str
    horizon_bars: int = 1
    cost_fraction: float = 0.0002
    noise_margin: float = 0.25
    allow_short: bool = True
    name = 'forecast_signal'

    def __post_init__(self):
        if type(self.horizon_bars) is not int or self.horizon_bars < 1:
            raise ValueError('horizon_bars must be an integer >= 1')
        if not (math.isfinite(self.cost_fraction) and self.cost_fraction >= 0
                and math.isfinite(self.noise_margin) and self.noise_margin >= 0):
            raise ValueError('cost_fraction and noise_margin must be finite and non-negative')

    @property
    def lookback(self):
        return 1

    def params(self):
        return {'forecast_sha256': self.book.sha256, 'symbol': self.symbol, 'model': self.model,
                'horizon_bars': str(self.horizon_bars), 'cost_fraction': repr(self.cost_fraction),
                'noise_margin': repr(self.noise_margin), 'allow_short': str(self.allow_short)}

    def target(self, history):
        candle = _history(history, 1)[-1]
        row = self.book.lookup(self.symbol, self.model, self.horizon_bars, candle.timestamp_ms)
        if row is None:
            return Signal.FLAT
        close = float(candle.close)
        if abs(row['last_close'] - close) > 1e-9 * close:
            return Signal.FLAT                      # the model saw different data than this dataset: fail closed
        edge = math.log(row['q50'] / close)
        noise = math.log(row['q90'] / row['q10']) / Z80
        threshold = self.cost_fraction + self.noise_margin * noise
        if edge > threshold:
            return Signal.LONG
        if edge < -threshold and self.allow_short:
            return Signal.SHORT
        return Signal.FLAT


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def _correlation(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return cov / math.sqrt(va * vb) if va > 0 and vb > 0 else None


def evaluate_forecasts(book, dataset, symbol, model, horizon_bars=1, start_ms=None, end_ms=None):
    """Compare forecasts with what happened. Use only on development data (end_ms before the locked holdout)."""
    index = {c.timestamp_ms: i for i, c in enumerate(dataset.candles)}
    pred, real, hits, abs_model, abs_zero, covered, n = [], [], 0, 0.0, 0.0, 0, 0
    signed = 0
    for row in book.rows(symbol, model, horizon_bars):
        i = index.get(row['decision_ts_ms'])
        if i is None or i + horizon_bars >= len(dataset.candles):
            continue
        if (start_ms is not None and row['decision_ts_ms'] < start_ms) or (
                end_ms is not None and dataset.candles[i + horizon_bars].timestamp_ms > end_ms):
            continue
        close, future = float(dataset.candles[i].close), float(dataset.candles[i + horizon_bars].close)
        p, r = math.log(row['q50'] / close), math.log(future / close)
        pred.append(p), real.append(r)
        abs_model += abs(r - p)
        abs_zero += abs(r)
        covered += row['q10'] <= future <= row['q90']
        if p != 0 and r != 0:
            signed += 1
            hits += (p > 0) == (r > 0)
        n += 1
    if n < 30:
        raise ForecastError('Only %d scored forecasts; at least 30 are needed' % n)
    return {'scored': n, 'directional_accuracy': hits / signed if signed else None,
            'rank_ic': _correlation(_ranks(pred), _ranks(real)),
            'mae_model': abs_model / n, 'mae_zero_forecast': abs_zero / n,
            'beats_zero_forecast': abs_model < abs_zero,
            'coverage_q10_q90': covered / n, 'coverage_target': 0.8}


def scored_rows(book, dataset, symbol, model, horizon_bars=1, end_ms=None):
    """(predicted log return, realised log return, realised price inside q10..q90, abs error) per scored forecast."""
    index = {c.timestamp_ms: i for i, c in enumerate(dataset.candles)}
    out = []
    for row in book.rows(symbol, model, horizon_bars):
        i = index.get(row['decision_ts_ms'])
        if i is None or i + horizon_bars >= len(dataset.candles):
            continue
        if end_ms is not None and dataset.candles[i + horizon_bars].timestamp_ms > end_ms:
            continue
        close, future = float(dataset.candles[i].close), float(dataset.candles[i + horizon_bars].close)
        out.append((math.log(row['q50'] / close), math.log(future / close), row['q10'] <= future <= row['q90']))
    return out
