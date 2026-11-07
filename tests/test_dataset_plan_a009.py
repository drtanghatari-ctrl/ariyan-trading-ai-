"""Reservation binds bytes/settings without evaluating either range."""
import copy
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import ROUND_DOWN, localcontext
from pathlib import Path
from unittest.mock import patch
from ariyan_trading.dataset_plan import (
    MAX_PLAN_BYTES, build_dataset_plan, read_dataset_plan, verify_dataset_plan,
)
from ariyan_trading.market_data import HEADER, load_candles
from ariyan_trading.replay import ReplayConfig

ROOT = Path(__file__).resolve().parents[1]

class DatasetPlanA009Tests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.csv = self.folder / 'candles.csv'
        self.csv.write_text(','.join(HEADER) + '\n' + ''.join(
            f'{i * 60000},100,110,90,105,1\n' for i in range(25)), encoding='utf-8')
        self.options = dict(symbol='BTCUSDT', interval_ms=60000,
                            source='SYNTHETIC TEST ONLY', as_of_ms=1500000)
        self.dataset = load_candles(self.csv, **self.options)

    def build(self, **kwargs):
        return build_dataset_plan(self.dataset, development_candles=12, **kwargs)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'ariyan_trading.dataset_plan',
            '--csv', str(self.csv), '--symbol', 'BTCUSDT', '--source', self.options['source'],
            '--interval-ms', '60000', '--as-of-ms', '1500000', *map(str, args)],
            cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'app')},
            capture_output=True, text=True)

    def test_ranges_hash_warmup_and_verification(self):
        plan = self.build()
        a, b = plan['ranges']
        self.assertEqual((a['start_index'], a['end_index_exclusive']), (0, 12))
        self.assertEqual((b['start_index'], b['end_index_exclusive']), (12, 25))
        self.assertEqual(a['last_close_ms'], b['first_open_ms'])
        self.assertEqual(a['first_eligible_fill_ms'], 300000)
        self.assertEqual(b['first_eligible_fill_ms'], 1020000)
        self.assertEqual(a['candles'] + b['candles'], 25)
        self.assertEqual(plan['dataset']['raw_sha256'], hashlib.sha256(self.csv.read_bytes()).hexdigest())
        self.assertFalse(plan['live_authorized'])
        self.assertFalse(plan['reservation_enforced_by_runtime'])
        self.assertEqual(verify_dataset_plan(self.dataset, plan), plan)

    def test_no_replay_or_performance(self):
        with patch('ariyan_trading.replay.run_replay', side_effect=AssertionError('No replay')):
            plan = self.build()
            verify_dataset_plan(self.dataset, plan)
        self.assertFalse({'summary', 'trades', 'return_pct', 'equity_curve'} & plan.keys())

    def test_minimum_ranges_and_invalid_inputs(self):
        small = replace(self.dataset, candles=self.dataset.candles[:12])
        self.assertEqual(build_dataset_plan(small, development_candles=6)['ranges'][1]['candles'], 6)
        for boundary in (True, 0, -1, 5, 20, 25, 100, '12', 12.0):
            with self.subTest(boundary=boundary), self.assertRaises(ValueError):
                build_dataset_plan(self.dataset, development_candles=boundary)
        with self.assertRaises(ValueError):
            build_dataset_plan(object(), development_candles=12)
        with self.assertRaises(ValueError):
            self.build(config={})

    def test_frozen_costs_and_config_validation(self):
        config = ReplayConfig(short_window=2, long_window=4, fee_bps='12')
        plan = self.build(config=config, stress_fee_bps='25', stress_slippage_bps='8')
        self.assertEqual(plan['config']['fee_bps'], '12')
        self.assertEqual(plan['stress_config']['fee_bps'], '25')
        self.assertEqual(plan['stress_config']['long_window'], 4)
        for options in (dict(stress_fee_bps='9'), dict(stress_slippage_bps='4'),
                        dict(stress_fee_bps='10', stress_slippage_bps='5'),
                        dict(stress_fee_bps='NaN'), dict(stress_fee_bps='1001')):
            with self.subTest(options=options), self.assertRaises((ValueError, ArithmeticError)):
                self.build(**options)

    def test_access_declarations_remain_unverified(self):
        for declaration in ('unknown', 'previously_inspected', 'caller_declares_not_inspected'):
            plan = self.build(prior_data_access=declaration)
            self.assertEqual(plan['prior_data_access'], declaration)
            self.assertEqual(plan['out_of_sample_status'], 'NOT_ESTABLISHED_CALLER_ASSERTION_ONLY')
        with self.assertRaises(ValueError):
            self.build(prior_data_access='verified_unseen')

    def test_changed_bytes_or_metadata_rejected(self):
        plan = self.build()
        self.csv.write_bytes(self.csv.read_bytes().replace(b'\n', b'\r\n'))
        same_prices = load_candles(self.csv, **self.options)
        self.assertEqual(self.dataset.candles, same_prices.candles)
        with self.assertRaises(ValueError):
            verify_dataset_plan(same_prices, plan)
        for kwargs in (dict(symbol='ETHUSDT'), dict(source='other'), dict(as_of_ms=1500001)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                verify_dataset_plan(replace(self.dataset, **kwargs), plan)

    def test_schema_tampering_and_type_confusion_rejected(self):
        mutations = [lambda p: p.update(live_authorized=0), lambda p: p.update(extra='unexpected'),
            lambda p: p.update(version='other'), lambda p: p['ranges'][1].update(start_index=11),
            lambda p: p['ranges'][0].update(first_open_ms=False),
            lambda p: p['stress_config'].update(long_window=9),
            lambda p: p['config'].update(long_window=True), lambda p: p.pop('limitations')]
        for mutation in mutations:
            plan = copy.deepcopy(self.build())
            mutation(plan)
            with self.assertRaises(ValueError):
                verify_dataset_plan(self.dataset, plan)
        for malformed in (None, [], {}, {'config': []}):
            with self.assertRaises(ValueError):
                verify_dataset_plan(self.dataset, malformed)

    def test_decimal_context_isolation(self):
        expected = self.build()
        with localcontext() as context:
            context.prec = 2
            context.rounding = ROUND_DOWN
            self.assertEqual(self.build(), expected)
            self.assertEqual(verify_dataset_plan(self.dataset, expected), expected)

    def test_strict_bounded_json(self):
        path = self.folder / 'bad.json'
        for raw in (b'{"key":1,"key":2}', b'{"key":NaN}', b'{"key":Infinity}',
                    b'{"key":-Infinity}', b'\xff', b'{', b' ' * (MAX_PLAN_BYTES + 1)):
            path.write_bytes(raw)
            with self.subTest(raw=raw[:30]), self.assertRaises((ValueError, UnicodeError)):
                read_dataset_plan(path)

    def test_cli_determinism_verify_and_no_overwrite(self):
        paths = [self.folder / 'first.json', self.folder / 'second.json']
        for path in paths:
            result = self.cli('create', '--development-candles', 12, '--output', path)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
        self.assertEqual(self.cli('verify', '--plan', paths[0]).returncode, 0)
        original = paths[0].read_bytes()
        self.assertEqual(self.cli('create', '--development-candles', 12, '--output', paths[0]).returncode, 2)
        self.assertEqual(paths[0].read_bytes(), original)
        csv_before = self.csv.read_bytes()
        self.assertEqual(self.cli('create', '--development-candles', 12, '--output', self.csv).returncode, 2)
        self.assertEqual(self.csv.read_bytes(), csv_before)
        self.csv.write_bytes(csv_before.replace(b'105', b'106'))
        self.assertEqual(self.cli('verify', '--plan', paths[0]).returncode, 2)

    def test_cli_failure_creates_no_plan(self):
        output = self.folder / 'absent.json'
        for boundary in (0, 5, 20):
            result = self.cli('create', '--development-candles', boundary, '--output', output)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())
        path = self.folder / 'invalid.json'
        path.write_text('{"config":1,"config":2}')
        self.assertEqual(self.cli('verify', '--plan', path).returncode, 2)

    def test_existing_real_fixture_smoke(self):
        path = ROOT / 'examples/a007/BTCUSDT-1h-2024-01-01.csv'
        dataset = load_candles(path, symbol='BTCUSDT', interval_ms=3600000,
            source='Existing real fixture; already inspected; smoke only',
            as_of_ms=1704153600000, input_format='binance-spot')
        plan = build_dataset_plan(dataset, development_candles=12, prior_data_access='previously_inspected')
        self.assertEqual(plan['ranges'][1]['candles'], 12)
        self.assertEqual(verify_dataset_plan(dataset, plan), plan)

if __name__ == '__main__':
    unittest.main()
