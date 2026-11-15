"""A046 tests: forecast file validation, signal rule, fail-closed behaviour, forecast-quality metrics."""
import os
import tempfile
import unittest
from decimal import Decimal as D

from ariyan_trading.forecast_signals import (
    HEADER, ForecastBook, ForecastError, ForecastSignal, evaluate_forecasts, load_forecasts, naive_forecast,
    parse_forecasts,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.strategies import Signal

DAY = 86_400_000


def candles(closes):
    return tuple(Candle(i * DAY, D(str(c)), D(str(c)), D(str(c)), D(str(c)), D(1)) for i, c in enumerate(closes))


def dataset(closes):
    return CandleDataset(candles(closes), 'T', DAY, 'S', (len(closes) + 1) * DAY, 'e' * 64, 'canonical', 'ms')


def line(ts, close, q10, q50, q90, model='m', symbol='T', ctx=None, horizon=1):
    return ','.join(str(x) for x in (ts, symbol, horizon, close, q10, q50, q90, model, 'v1', ts if ctx is None else ctx))


def raw(*lines):
    return ('\n'.join([','.join(HEADER)] + list(lines)) + '\n').encode()


def book(*lines):
    return ForecastBook(parse_forecasts(raw(*lines)), 'a' * 64)


class ParsingTests(unittest.TestCase):
    def test_valid_file_and_hash_from_disk(self):
        data = raw(line(0, 100, 99, 100.5, 102))
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as handle:
            handle.write(data)
        self.addCleanup(os.unlink, handle.name)
        loaded = load_forecasts(handle.name)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(len(loaded.sha256), 64)
        self.assertEqual(loaded.lookup('T', 'm', 1, 0)['q50'], 100.5)

    def test_rejections(self):
        bad = {
            'quantile order': raw(line(0, 100, 101, 100, 102)),
            'look-ahead context': raw(line(0, 100, 99, 100, 102, ctx=DAY)),
            'non positive': raw(line(0, 100, 0, 100, 102)),
            'not a number': raw(line(0, 100, 99, 'nan', 102)),
            'infinite': raw(line(0, 100, 99, 'inf', 'inf')),
            'empty model': raw(line(0, 100, 99, 100, 102, model='')),
            'bad horizon': raw(line(0, 100, 99, 100, 102, horizon=0)),
            'no rows': raw(),
        }
        for name, data in bad.items():
            with self.assertRaises(ForecastError, msg=name):
                parse_forecasts(data)
        with self.assertRaises(ForecastError):
            parse_forecasts(b'a,b\n1,2\n')                       # wrong header
        with self.assertRaises(ForecastError):
            ForecastBook(parse_forecasts(raw(line(0, 100, 99, 100, 102), line(0, 100, 98, 100, 103))), 'a' * 64)


class SignalTests(unittest.TestCase):
    def signal(self, *lines, **kw):
        return ForecastSignal(book(*lines), 'T', 'm', **kw)

    def test_long_short_flat_by_edge_against_cost_and_noise(self):
        history = candles([100])
        # edge +1%, noise ~0.78%: threshold 0.0002 + 0.25*0.0078 = 0.00215 -> LONG
        self.assertIs(self.signal(line(0, 100, 99.2, 101, 100.8 + 0.4)).target(history), Signal.LONG)
        self.assertIs(self.signal(line(0, 100, 98.2, 99, 100.8)).target(history), Signal.SHORT)
        self.assertIs(self.signal(line(0, 100, 98.2, 99, 100.8), allow_short=False).target(history), Signal.FLAT)
        # edge +0.01% is below the cost: no trade region
        self.assertIs(self.signal(line(0, 100, 99, 100.01, 101)).target(history), Signal.FLAT)
        # same edge but a very wide interval (noisy) is rejected
        self.assertIs(self.signal(line(0, 100, 90, 100.5, 112)).target(history), Signal.FLAT)

    def test_fails_closed(self):
        sig = self.signal(line(0, 100, 99.2, 101, 101.2))
        self.assertIs(sig.target(candles([100, 100])), Signal.FLAT)             # no forecast for this bar
        self.assertIs(sig.target(candles([100.5])), Signal.FLAT)                # model saw a different close
        other = ForecastSignal(book(line(0, 100, 99.2, 101, 101.2)), 'T', 'other-model')
        self.assertIs(other.target(candles([100])), Signal.FLAT)                # wrong model name

    def test_params_identify_the_forecast_file_and_validation(self):
        sig = self.signal(line(0, 100, 99, 100, 101))
        self.assertEqual(sig.describe()['params']['forecast_sha256'], 'a' * 64)
        with self.assertRaises(ValueError):
            ForecastSignal(sig.book, 'T', 'm', cost_fraction=-1)
        with self.assertRaises(ValueError):
            ForecastSignal(sig.book, 'T', 'm', horizon_bars=0)
        with self.assertRaises(ValueError):
            ForecastSignal(sig.book, 'T', 'm', noise_margin=float('nan'))


class QualityTests(unittest.TestCase):
    def test_perfect_and_useless_forecasters(self):
        closes = [100 + (i % 7) * 1.5 - (i % 3) for i in range(80)]
        ds = dataset(closes)
        perfect = [line(i * DAY, closes[i], min(closes[i], closes[i + 1]) - 0.1, closes[i + 1],
                        max(closes[i], closes[i + 1]) + 0.1) for i in range(79)]
        out = evaluate_forecasts(book(*perfect), ds, 'T', 'm')
        self.assertEqual((out['scored'], out['directional_accuracy'], out['coverage_q10_q90']), (79, 1.0, 1.0))
        self.assertAlmostEqual(out['rank_ic'], 1.0, places=9)
        self.assertTrue(out['beats_zero_forecast'])
        flat = [line(i * DAY, closes[i], closes[i] - 1, closes[i], closes[i] + 1) for i in range(79)]
        out = evaluate_forecasts(book(*flat), ds, 'T', 'm')
        self.assertFalse(out['beats_zero_forecast'])             # predicting "no change" equals the zero forecast
        self.assertIsNone(out['directional_accuracy'])

    def test_too_few_and_window(self):
        closes = [100 + i % 5 for i in range(60)]
        ds = dataset(closes)
        rows = [line(i * DAY, closes[i], closes[i] - 1, closes[i], closes[i] + 1) for i in range(59)]
        with self.assertRaises(ForecastError):
            evaluate_forecasts(book(*rows[:10]), ds, 'T', 'm')
        with self.assertRaises(ForecastError):
            evaluate_forecasts(book(*rows), ds, 'T', 'm', end_ms=20 * DAY)   # only ~19 scored in window

    def test_naive_forecast(self):
        closes = [100 * 1.001 ** i * (1.01 if i % 2 else 0.99) for i in range(80)]
        low, mid, high = naive_forecast(closes)
        self.assertEqual(mid, closes[-1])
        self.assertLess(low, mid)
        self.assertLess(mid, high)
        with self.assertRaises(ForecastError):
            naive_forecast(closes[:10])


if __name__ == '__main__':
    unittest.main()
