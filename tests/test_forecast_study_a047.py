"""A047 tests: pre-registered pass marks applied to synthetic perfect, useless and miscalibrated forecasters."""
import random
import unittest

from ariyan_trading.forecast_signals import ForecastBook, parse_forecasts
from ariyan_trading.forecast_study import study
from tests.test_forecast_signals_a046 import DAY, dataset, line, raw


def closes(seed, n=400):
    rng, value, out = random.Random(seed), 100.0, []
    for _ in range(n):
        value *= 1 + rng.gauss(0, 0.01)
        out.append(round(value, 4))
    return out


def entries(kind, instruments=5, n=400):
    out = []
    for k in range(instruments):
        symbol, c, rows = 'S%d' % k, closes(k + 1, n), []
        for i in range(len(c) - 1):
            if kind == 'perfect':                                  # exact median; interval holds the outcome 80%
                q = (c[i + 1] - 0.3, c[i + 1], c[i + 1] + 0.3) if i % 5 else (
                    c[i + 1] + 0.00005, c[i + 1] + 0.0001, c[i + 1] + 0.00015)
            elif kind == 'flat':                                   # "no change", honest 80% interval
                q = (c[i] - 1.3, c[i], c[i] + 1.3)
            else:                                                  # noisy median, far too narrow interval
                noise = random.Random(k * 1000 + i).gauss(0, 0.3)
                q = (c[i] + noise - 0.05, c[i] + noise, c[i] + noise + 0.05)
            rows.append(line(i * DAY, c[i], round(q[0], 4), round(q[1], 4), round(q[2], 4), model='m', symbol='S%d' % k))
        out.append({'symbol': symbol, 'dataset': dataset(c),
                    'book': ForecastBook(parse_forecasts(raw(*rows)), 'a' * 64), 'model': 'm'})
    return out


class StudyTests(unittest.TestCase):
    def test_perfect_forecaster_passes_every_mark(self):
        result = study(entries('perfect'), bootstrap=60)
        self.assertEqual(result['verdict'], 'PASS', result['marks'])
        self.assertEqual(result['pooled']['instruments'], 5)

    def test_unskilled_forecasters_fail(self):
        flat = study(entries('flat'), bootstrap=60)
        self.assertEqual(flat['verdict'], 'FAIL')
        self.assertFalse(flat['marks']['mark1_rank_ic'])
        noisy = study(entries('noisy'), bootstrap=60)
        self.assertEqual(noisy['verdict'], 'FAIL')
        self.assertFalse(noisy['marks']['mark4_calibration'])      # overconfident interval
        self.assertFalse(noisy['marks']['mark3_beats_zero_forecast'])

    def test_results_are_reproducible_and_need_enough_data(self):
        a = study(entries('noisy'), bootstrap=40, seed=3)
        b = study(entries('noisy'), bootstrap=40, seed=3)
        self.assertEqual(a['pooled']['rank_ic_interval'], b['pooled']['rank_ic_interval'])
        with self.assertRaises(ValueError):
            study(entries('perfect', n=60))
        with self.assertRaises(ValueError):
            study([])


if __name__ == '__main__':
    unittest.main()
