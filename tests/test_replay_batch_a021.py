"""Synthetic batch integration tests; no market-support or profitability evidence."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from decimal import Inexact, localcontext
from pathlib import Path
from unittest.mock import patch

from test_session_replay_a017 import series as fixture, config as configuration
from symlink_fixture import symlink_or_skip

from ariyan_trading import replay_batch as batch
from ariyan_trading.instruments import InstrumentIdentity, AssetClass as A, ProductType as P, SettlementType as S
from ariyan_trading.market_data import HEADER, load_candles
from ariyan_trading.sessions import SessionSchedule, SessionWindow, CoverageKind
from ariyan_trading.session_replay import run_session_replay

ROOT = Path(__file__).resolve().parents[1]


class ReplayBatchA021Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.manifest = self.root / 'jobs.json'
        self.output = self.root / 'batch.json'
        self.expected = []
        self.request = {'version': batch.REQUEST_VERSION, 'jobs': [self.job('stock'), self.job('crypto', A.CRYPTO)]}
        self.save()

    def job(self, label, asset=A.EQUITY, currency=None, venue='SYNTHETIC', prices=None):
        series = fixture() if prices is None else fixture(prices)
        spec = series.spec
        if asset in (A.CRYPTO, A.METAL, A.ENERGY):
            unit = {A.CRYPTO: 'COIN', A.METAL: 'OUNCE', A.ENERGY: 'BARREL'}[asset]
            currency = currency or 'USDT'
            spec = replace(spec, asset_class=asset, product=P.SPOT, quantity_unit=unit,
                price_unit=currency+'_PER_'+unit, quote_currency=currency, settlement_currency=currency,
                settlement_type=S.ASSET_DELIVERY, corporate_action_reference='NOT_APPLICABLE')
        elif asset is A.FUND:
            spec = replace(spec, asset_class=asset, product=P.FUND_SHARE)
        if currency is not None:
            spec = replace(spec, quote_currency=currency, settlement_currency=currency,
                           price_unit=currency+'_PER_'+spec.quantity_unit)
        spec = replace(spec, identity=InstrumentIdentity(venue, label), display_symbol='SAME')
        series = replace(series, spec=spec, volume_unit=spec.quantity_unit)
        folder = self.root / label
        folder.mkdir()
        csv = folder/'candles.csv'
        csv.write_text(','.join(HEADER)+'\n'+''.join(','.join(str(v) for v in
            (b.timestamp_ms, b.open, b.high, b.low, b.close, b.volume))+'\n' for b in series.candles))
        (folder/'instrument.json').write_text(json.dumps(spec.to_record()))
        (folder/'schedule.json').write_text(json.dumps(series.schedule.to_record()))
        config = configuration(cash_currency=spec.quote_currency)
        self.expected.append((replace(series, raw_sha256=hashlib.sha256(csv.read_bytes()).hexdigest()), config))
        return {'job_id': label, 'csv': label+'/candles.csv', 'instrument': label+'/instrument.json',
                'schedule': label+'/schedule.json',
                'intake': {name: getattr(series, name) for name in batch.INTAKE_FIELDS},
                'config': asdict(config)}

    def save(self):
        self.manifest.write_text(json.dumps(self.request, sort_keys=True))

    def run_batch(self, output=None):
        return batch.run_batch(self.manifest, output or self.output)

    def reject(self):
        with self.assertRaises((ValueError, TypeError, OSError, KeyError)):
            self.run_batch()
        self.assertFalse(self.output.exists())

    def process(self, output=None):
        return subprocess.run([sys.executable, '-m', 'ariyan_trading.replay_batch',
            '--manifest', str(self.manifest), '--output', str(output or self.output)],
            cwd=self.root, env={**os.environ, 'PYTHONPATH': str(ROOT/'app')}, capture_output=True, text=True)

    def test_exact_agreement_with_independent_engine_runs_and_summary_rows(self):
        original = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        report = self.run_batch()
        self.assertEqual(report['job_count'], 2)
        for index, (series, config) in enumerate(self.expected):
            replay = run_session_replay(series, config)
            self.assertEqual(report['jobs'][index]['replay'], replay)
            row = report['summary_table'][index]
            self.assertEqual(row['return_pct'], replay['summary']['return_pct'])
            self.assertEqual(row['filled_orders'], len(replay['trades']))
            self.assertEqual(row['cash_currency'], config.cash_currency)
        self.assertEqual(original, {p: p.read_bytes() for p in original})

    def test_cash_risk_signals_and_currencies_do_not_cross_jobs(self):
        first = self.run_batch()
        self.request['jobs'][0]['config'].update(opening_cash='50', max_close_drawdown_pct='1')
        self.save()
        second = self.run_batch(self.root/'other.json')
        self.assertEqual(first['jobs'][1], second['jobs'][1])
        self.assertNotEqual(first['jobs'][0]['replay']['summary'], second['jobs'][0]['replay']['summary'])
        self.assertEqual([r['cash_currency'] for r in second['summary_table']], ['USD', 'USDT'])

    def test_crypto_stock_fund_metal_energy_use_explicit_cash_terms(self):
        self.request['jobs'] += [self.job('fund', A.FUND), self.job('gold', A.METAL),
                                  self.job('silver', A.METAL), self.job('oil', A.ENERGY)]
        self.save()
        report = self.run_batch()
        self.assertEqual(report['job_count'], 6)
        self.assertEqual({r['replay']['intake']['instrument']['asset_class'] for r in report['jobs']},
                         {'CRYPTO', 'EQUITY', 'FUND', 'METAL', 'ENERGY'})
        for job in report['jobs']:
            self.assertFalse(job['replay']['live_authorized'])

    def test_display_symbol_collision_never_substitutes_instrument_identity(self):
        path = self.root/'crypto/instrument.json'
        record = json.loads(path.read_bytes())
        record['identity'] = {'venue': 'OTHER-VENUE', 'venue_instrument_id': 'stock'}
        path.write_text(json.dumps(record))
        report = self.run_batch()
        self.assertEqual(report['jobs'][0]['replay']['intake']['instrument']['display_symbol'], 'SAME')
        self.assertNotEqual(report['jobs'][0]['instrument_identity_sha256'], report['jobs'][1]['instrument_identity_sha256'])

    def test_job_order_preserved_reordering_does_not_change_individual_replays(self):
        first = self.run_batch()
        self.request['jobs'].reverse()
        self.save()
        second = self.run_batch(self.root/'reverse.json')
        self.assertEqual(first['jobs'], list(reversed(second['jobs'])))

    def test_same_instrument_variants_remain_separate_named_jobs(self):
        variant = copy.deepcopy(self.request['jobs'][0])
        variant['job_id'] = 'stock-stress'
        variant['config']['fee_bps'] = '20'
        self.request['jobs'].append(variant)
        self.save()
        report = self.run_batch()
        self.assertEqual(report['job_count'], 3)
        self.assertEqual(report['jobs'][0]['instrument_identity_sha256'], report['jobs'][2]['instrument_identity_sha256'])
        self.assertEqual(report['jobs'][2]['replay']['config']['fee_bps'], '20')

    def test_strict_schema_version_count_and_duplicate_job_ids(self):
        original = copy.deepcopy(self.request)
        bad = [[], {}, {**original, 'live_authorized': True}, {**original, 'version': 'future'},
               {**original, 'jobs': []}, {**original, 'jobs': original['jobs']*5},
               {**original, 'jobs': [original['jobs'][0]]*2}]
        for request in bad:
            self.request = request
            self.save()
            self.reject()

    def test_job_intake_config_types_and_unknown_fields_fail_before_replay(self):
        original = copy.deepcopy(self.request)
        mutations = [('job', 'job_id', '../bad'), ('job', 'csv', 1), ('job', 'new', True),
            ('intake', 'interval_ms', True), ('intake', 'as_of_ms', '100'),
            ('config', 'fee_bps', 10), ('config', 'long_window', True),
            ('config', 'max_trades', 1.0), ('config', 'cash_step', 'NaN')]
        for section, key, value in mutations:
            self.request = copy.deepcopy(original)
            target = self.request['jobs'][1]
            (target if section == 'job' else target[section])[key] = value
            self.save()
            with patch.object(batch, 'run_session_replay') as replay:
                self.reject()
                replay.assert_not_called()
        self.request = copy.deepcopy(original)
        del self.request['jobs'][0]['config']['fee_bps']
        self.save()
        self.reject()

    def test_duplicate_json_keys_nonfinite_and_nonobject_metadata_rejected(self):
        original = self.manifest.read_bytes()
        for raw in ('{"version":1,"version":2}', '{"jobs":NaN}', '[]', '{bad'):
            self.manifest.write_text(raw)
            self.reject()
        self.manifest.write_bytes(original)
        (self.root/'crypto/instrument.json').write_text('[]')
        self.reject()

    def test_later_job_failure_publishes_no_partial_batch(self):
        csv = self.root/'crypto/candles.csv'
        lines = csv.read_text().splitlines()
        csv.write_text('\n'.join(lines[:4]+lines[5:])+'\n')
        self.reject()
        self.assertEqual(list(self.root.glob('batch*')), [])

    def test_futures_and_currency_mismatch_remain_rejected(self):
        self.request['jobs'][1]['config']['cash_currency'] = 'EUR'
        self.save()
        self.reject()
        self.request['jobs'][1]['config']['cash_currency'] = 'USDT'
        path = self.root/'crypto/instrument.json'
        record = json.loads(path.read_bytes())
        record.update(product='FUTURE', quantity_unit='CONTRACT', contract_multiplier='100',
            last_trade_ms=12*3600000, expiry_ms=12*3600000, settlement_type='CASH', roll_reference='SYNTHETIC-ROLL')
        self.request['jobs'][1]['intake']['volume_unit'] = 'CONTRACT'
        self.save()
        path.write_text(json.dumps(record))
        self.reject()

    def test_byte_slot_and_report_limits_reject_without_output(self):
        for name in ('MAX_MANIFEST_BYTES', 'MAX_TOTAL_INPUT_BYTES', 'MAX_TOTAL_GRID_SLOTS', 'MAX_REPORT_BYTES'):
            with patch.object(batch, name, 1):
                self.reject()
        for name in ('MAX_SPEC_BYTES', 'MAX_SCHEDULE_BYTES'):
            with patch.object(batch.files, name, 1):
                self.reject()

    def test_missing_files_parent_symlinks_and_nonregular_inputs_rejected(self):
        with self.assertRaises(ValueError):
            self.run_batch(self.root/'absent/report.json')
        self.assertFalse((self.root/'absent').exists())
        with self.subTest(symlink='batch manifest'):
            linked = self.root/'linked.json'
            symlink_or_skip(linked, self.manifest)
            with self.assertRaises(ValueError):
                batch.run_batch(linked, self.output)
        self.request['jobs'][1]['csv'] = 'crypto'
        self.save()
        self.reject()
        self.request['jobs'][1]['csv'] = 'not-found.csv'
        self.save()
        self.reject()

    def test_existing_output_and_every_input_are_preserved(self):
        self.output.write_bytes(b'keep')
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertEqual(self.output.read_bytes(), b'keep')
        for path in [self.manifest, *self.root.glob('*/*.json'), *self.root.glob('*/*.csv')]:
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                self.run_batch(path)
            self.assertEqual(path.read_bytes(), before)

    def test_any_job_or_manifest_change_during_run_prevents_publication(self):
        original = batch.run_session_replay
        for target in (self.manifest, self.root/'stock/candles.csv', self.root/'crypto/instrument.json',
                       self.root/'crypto/schedule.json'):
            before = target.read_bytes()
            def changed(series, config):
                result = original(series, config)
                target.write_bytes(before+b' ')
                return result
            with patch.object(batch, 'run_session_replay', side_effect=changed):
                self.reject()
            target.write_bytes(before)

    def test_source_change_prevents_publication(self):
        source = batch._sources()
        with patch.object(batch, '_sources', side_effect=[source, {**source, 'replay_batch.py': '0'*64}]):
            self.reject()

    def test_output_creation_race_preserves_other_writers_file(self):
        original = batch.files._write
        def racing(path, raw):
            path.write_bytes(b'other writer')
            return original(path, raw)
        with patch.object(batch.files, '_write', side_effect=racing):
            with self.assertRaises(FileExistsError):
                self.run_batch()
        self.assertEqual(self.output.read_bytes(), b'other writer')

    def test_failed_write_removes_owned_partial_output_only(self):
        original = Path.open
        target = self.output
        class Broken:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, raw):
                self.stream.write(raw[:10])
                raise OSError('Synthetic output interruption')
        def broken(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return Broken(stream) if path == target and args and args[0] == 'xb' else stream
        before = self.manifest.read_bytes()
        with patch.object(Path, 'open', new=broken):
            self.reject()
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_deterministic_fresh_processes_and_unsigned_batch_hash(self):
        first = self.process()
        self.assertEqual(first.returncode, 0, first.stderr)
        other = self.root/'other.json'
        second = self.process(other)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())
        report = json.loads(self.output.read_bytes())
        digest = report.pop('batch_sha256')
        self.assertEqual(digest, hashlib.sha256(batch.VERSION.encode()+b'\0'+batch.files._canonical(report)).hexdigest())
        self.assertIn('INDEPENDENT ACCOUNTS', first.stdout)

    def test_context_isolation_and_no_portfolio_or_authority_claims(self):
        report = self.run_batch()
        with localcontext() as context:
            context.prec = 2
            context.traps[Inexact] = True
            self.assertEqual(report, self.run_batch(self.root/'context.json'))
        for name in ('portfolio_aggregation_performed', 'fx_conversion_performed', 'parameter_search_performed',
                     'strategy_promoted', 'source_independently_authenticated', 'ledger_posted', 'live_authorized'):
            self.assertIs(report[name], False)
        self.assertEqual(report['out_of_sample_status'], 'NOT_ESTABLISHED')
        self.assertNotIn('portfolio_return_pct', report)

    def test_cli_rejection_returns_two_and_no_report(self):
        self.manifest.write_text('{bad')
        with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as raised:
            batch.main(['--manifest', str(self.manifest), '--output', str(self.output)])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.output.exists())

    def test_real_btc_fixture_base_and_stress_smoke_only(self):
        start, end = 1704067200000, 1704153600000
        real = load_candles(ROOT/'examples/a007/BTCUSDT-1h-2024-01-01.csv', symbol='BTCUSDT',
            source='EXISTING REAL FIXTURE; SMOKE ONLY', interval_ms=3600000, as_of_ms=end,
            input_format='binance-spot')
        job = self.job('btc-smoke', A.CRYPTO)
        template, config = self.expected[-1]
        spec = replace(template.spec, quantity_unit='BTC', price_unit='USDT_PER_BTC',
            price_step='0.00000001', quantity_step='0.00000001', minimum_quantity='0.00000001',
            effective_from_ms=start, effective_until_ms=end, observed_at_ms=end)
        schedule = SessionSchedule('SYNTHETIC-V1', 'UTC', start, end, CoverageKind.EXHAUSTIVE,
            (SessionWindow(start, end, 'SYNTHETIC FULL DAY'),), 'UNVERIFIED CALENDAR; SMOKE ONLY', end)
        series = replace(template, candles=real.candles, spec=spec, schedule=schedule, symbol='BTCUSDT',
            volume_unit='BTC', first_open_ms=start, end_exclusive_ms=end, as_of_ms=end,
            source='EXISTING REAL FIXTURE; SMOKE ONLY')
        folder = self.root/'btc-smoke'
        (folder/'instrument.json').write_text(json.dumps(spec.to_record()))
        (folder/'schedule.json').write_text(json.dumps(schedule.to_record()))
        (folder/'candles.csv').write_text(','.join(HEADER)+'\n'+''.join(','.join(str(v) for v in
            (b.timestamp_ms, b.open, b.high, b.low, b.close, b.volume))+'\n' for b in series.candles))
        job['intake'] = {name: getattr(series, name) for name in batch.INTAKE_FIELDS}
        stress = copy.deepcopy(job)
        stress['job_id'] = 'btc-smoke-stress'
        stress['config'].update(fee_bps='20', slippage_bps='20')
        self.request['jobs'] = [job, stress]
        self.save()
        report = self.run_batch()
        for item in report['jobs']:
            self.assertEqual(item['replay']['intake']['candles'], 24)
            self.assertEqual(item['input_bytes_sha256']['csv'], hashlib.sha256((folder/'candles.csv').read_bytes()).hexdigest())
            self.assertNotEqual(item['input_bytes_sha256']['csv'], real.raw_sha256)
        self.assertFalse(report['source_independently_authenticated'])

    def test_latched_halt_is_local_to_its_account(self):
        self.request['jobs'][0]['config']['max_close_drawdown_pct'] = '0.01'
        self.save()
        report = self.run_batch()
        self.assertTrue(report['jobs'][0]['replay']['summary']['drawdown_halted'])
        self.assertFalse(report['jobs'][1]['replay']['summary']['drawdown_halted'])


if __name__ == '__main__':
    unittest.main()
