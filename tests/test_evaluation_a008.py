import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal, localcontext, Inexact

from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.replay import ReplayConfig, run_replay
from ariyan_trading.evaluation import evaluate_periods

ROOT = Path(__file__).resolve().parents[1]


def dataset(count=25):
    bars = []
    for i in range(count):
        price = Decimal(100 + (i % 9))
        bars.append(Candle(i * 1000, price, price + 2, price - 2, price + 1, Decimal(10)))
    return CandleDataset(tuple(bars), 'TEST', 1000, 'synthetic test only',
                         count * 1000, 'a' * 64, 'canonical', 'ms')


class EvaluationTests(unittest.TestCase):
    def test_partition_covers_every_bar_once(self):
        report = evaluate_periods(dataset())
        self.assertEqual([(x['start_index'], x['end_index_exclusive']) for x in report['periods']],
                         [(0, 9), (9, 17), (17, 25)])
        self.assertEqual(sum(x['candles'] for x in report['periods']), 25)
        for previous, following in zip(report['periods'], report['periods'][1:]):
            self.assertEqual(previous['last_close_ms'], following['first_open_ms'])

    def test_each_scenario_matches_independent_replay(self):
        data = dataset()
        config = ReplayConfig()
        report = evaluate_periods(data, config)
        for period in report['periods']:
            subset = replace(data, candles=data.candles[period['start_index']:period['end_index_exclusive']])
            for name, cfg in [('base', config), ('stress', replace(config, fee_bps='20', slippage_bps='10'))]:
                expected = run_replay(subset, cfg)
                self.assertEqual(period['scenarios'][name]['summary'], expected['summary'])
                self.assertEqual(period['scenarios'][name]['buy_hold'], expected['buy_hold'])
            self.assertEqual(period['first_eligible_fill_ms'], subset.candles[5].timestamp_ms)

    def test_later_prices_cannot_change_earlier_period(self):
        data = dataset()
        changed = tuple(replace(c, open=c.open * 2, high=c.high * 2,
                                low=c.low * 2, close=c.close * 2) if i >= 9 else c
                        for i, c in enumerate(data.candles))
        self.assertEqual(evaluate_periods(data)['periods'][0],
                         evaluate_periods(replace(data, candles=changed))['periods'][0])

    def test_period_resets_without_previous_signal_or_capital(self):
        data = dataset()
        changed = tuple(replace(c, open=c.open * 3, high=c.high * 3,
                                low=c.low * 3, close=c.close * 3) if i < 9 else c
                        for i, c in enumerate(data.candles))
        self.assertEqual(evaluate_periods(data)['periods'][1:],
                         evaluate_periods(replace(data, candles=changed))['periods'][1:])

    def test_counts_and_provenance_do_not_claim_approval(self):
        report = evaluate_periods(dataset())
        self.assertFalse(report['live_authorized'])
        self.assertIn('NOT_ESTABLISHED', report['out_of_sample_status'])
        self.assertEqual(report['dataset']['raw_sha256'], 'a' * 64)
        for name in ['base', 'stress']:
            self.assertEqual(sum(report['period_counts'][name].values()), 3)
            pnl = [Decimal(p['scenarios'][name]['summary']['net_marked_pnl']) for p in report['periods']]
            self.assertEqual(report['period_counts'][name]['positive_periods'], sum(x > 0 for x in pnl))

    def test_decimal_context_and_repeatability(self):
        data = dataset()
        expected = evaluate_periods(data)
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.traps[Inexact] = True
            self.assertEqual(evaluate_periods(data), expected)
        json.dumps(expected, allow_nan=False)

    def test_invalid_inputs_and_short_periods(self):
        for periods in [True, 1, 21, 2.0, '3', None]:
            with self.subTest(periods=periods), self.assertRaises(ValueError):
                evaluate_periods(dataset(), periods=periods)
        with self.assertRaises(ValueError):
            evaluate_periods(dataset(17))
        with self.assertRaises(ValueError):
            evaluate_periods(None)
        with self.assertRaises(ValueError):
            evaluate_periods(dataset(), object())
        self.assertEqual(len(evaluate_periods(dataset(18))['periods']), 3)

    def test_cost_stress_must_increase_without_decreasing_other_cost(self):
        for fee, slip in [('10', '5'), ('9', '10'), ('20', '4'), ('1001', '10'), ('NaN', '10')]:
            with self.subTest(fee=fee, slip=slip), self.assertRaises(ValueError):
                evaluate_periods(dataset(), stress_fee_bps=fee, stress_slippage_bps=slip)
        evaluate_periods(dataset(), stress_fee_bps='10', stress_slippage_bps='6')


class EvaluationCliTests(unittest.TestCase):
    def command(self, output):
        return [sys.executable, '-m', 'ariyan_trading.evaluation',
                '--csv', str(ROOT / 'examples/a007/BTCUSDT-1h-2024-01-01.csv'),
                '--format', 'binance-spot', '--symbol', 'BTCUSDT',
                '--source', 'real-data smoke only', '--interval-ms', '3600000',
                '--as-of-ms', '1704153600000', '--output', str(output)]

    def run_cli(self, args):
        return subprocess.run(args, cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'app')},
                              capture_output=True, text=True)

    def test_real_smoke_deterministic_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / 'a.json', Path(directory) / 'b.json'
            for output in [first, second]:
                result = self.run_cli(self.command(output))
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            data = json.loads(first.read_text())
            self.assertEqual([p['candles'] for p in data['periods']], [8, 8, 8])
            original = first.read_bytes()
            self.assertEqual(self.run_cli(self.command(first)).returncode, 2)
            self.assertEqual(first.read_bytes(), original)

    def test_rejected_input_creates_no_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'report.json'
            for extra in [['--periods', '20'], ['--stress-fee-bps', '1'], ['--long-window', '100']]:
                result = self.run_cli(self.command(output) + extra)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(output.exists())

    def test_input_path_cannot_be_overwritten(self):
        source = ROOT / 'examples/a007/BTCUSDT-1h-2024-01-01.csv'
        original = source.read_bytes()
        self.assertEqual(self.run_cli(self.command(source)).returncode, 2)
        self.assertEqual(source.read_bytes(), original)
