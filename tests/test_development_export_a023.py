"""Plan-bound export mechanics; synthetic prices except the retained BTC smoke."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Inexact, localcontext
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import development_export as export
from ariyan_trading.dataset_plan import build_dataset_plan
from ariyan_trading.market_data import HEADER, load_candles

ROOT = Path(__file__).resolve().parents[1]


class DevelopmentExportA023Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.csv = self.root/'original.csv'
        self.plan_path = self.root/'plan.json'
        self.destination = self.root/'development'
        self.options = dict(symbol='SYNTH', source='SYNTHETIC TEST ONLY', interval_ms=60000, as_of_ms=1500000)
        self.csv.write_text(','.join(HEADER)+'\n'+''.join(
            f'{i*60000},100.00,110.0,90,105.000,1.000\n' for i in range(25)))
        self.plan = self.replan()

    def replan(self):
        self.dataset = load_candles(self.csv, **self.options)
        plan = build_dataset_plan(self.dataset, development_candles=12, prior_data_access='previously_inspected')
        self.plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True)+'\n')
        return plan

    def run_export(self, destination=None):
        return export.export_development(self.csv, self.plan_path, destination or self.destination)

    def verify(self):
        return export.verify_development_export(self.csv, self.plan_path, self.destination)

    def reject(self):
        with self.assertRaises((ValueError, OSError, TypeError, KeyError)):
            self.run_export()
        self.assertFalse(self.destination.exists())

    def test_exact_development_values_boundaries_hashes_and_originals_preserved(self):
        original = {p:p.read_bytes() for p in (self.csv, self.plan_path)}
        receipt = self.run_export()
        self.assertEqual({p.name for p in self.destination.iterdir()}, set(export.NAMES))
        self.assertEqual((self.destination/'dataset-plan.json').read_bytes(), original[self.plan_path])
        selected = load_candles(self.destination/'development.csv', **self.options)
        self.assertEqual(selected.candles, self.dataset.candles[:12])
        self.assertTrue(all(b.timestamp_ms < self.plan['ranges'][1]['first_open_ms'] for b in selected.candles))
        self.assertEqual(receipt['exported_dataset']['raw_sha256'], selected.raw_sha256)
        self.assertEqual(receipt['original_dataset']['raw_sha256'], self.dataset.raw_sha256)
        self.assertEqual(receipt['original_plan_bytes_sha256'], hashlib.sha256(original[self.plan_path]).hexdigest())
        self.assertEqual(receipt['reserved_candles_exported'], 0)
        self.assertEqual({p:p.read_bytes() for p in original}, original)
        self.assertEqual(receipt, self.verify())

    def test_normalization_changes_bytes_without_changing_candle_values(self):
        receipt = self.run_export()
        raw = (self.destination/'development.csv').read_bytes()
        self.assertIn(b'0,100,110,90,105,1\n', raw)
        self.assertNotIn(b'100.00', raw)
        self.assertNotEqual(receipt['exported_dataset']['raw_sha256'], self.dataset.raw_sha256)

    def test_no_replay_strategy_selection_or_authority(self):
        with (patch('ariyan_trading.replay.run_replay', side_effect=AssertionError('No replay')),
                patch('ariyan_trading.session_replay.run_session_replay', side_effect=AssertionError('No replay'))):
            receipt = self.run_export()
        for field in ('performance_evaluated_by_this_operation', 'reserved_performance_evaluated_by_this_operation',
                'global_reservation_access_control_established', 'authenticated_plan_publication_established',
                'source_independently_authenticated', 'live_authorized', 'a017_configuration_derived'):
            self.assertIs(receipt[field], False)
        self.assertEqual(receipt['prior_data_access'], 'previously_inspected')
        self.assertEqual(receipt['out_of_sample_status'], 'NOT_ESTABLISHED_CALLER_ASSERTION_ONLY')
        self.assertEqual(receipt['config'], self.plan['config'])
        self.assertEqual(receipt['stress_config'], self.plan['stress_config'])
        self.assertFalse({'return_pct', 'trades', 'equity_curve', 'summary'} & receipt.keys())

    def test_modified_source_bytes_including_reserved_rows_rejected(self):
        raw = self.csv.read_bytes()
        self.csv.write_bytes(raw.replace(b'\n', b'\r\n'))
        self.reject()
        self.csv.write_bytes(raw)
        lines = self.csv.read_text().splitlines()
        lines[-1] = lines[-1].replace('105.000', '106')
        self.csv.write_text('\n'.join(lines)+'\n')
        self.reject()

    def test_invalid_reserved_ohlc_rejects_full_input_before_export(self):
        lines = self.csv.read_text().splitlines()
        lines[-1] = lines[-1].replace('105.000', '999')
        self.csv.write_text('\n'.join(lines)+'\n')
        self.reject()

    def test_plan_schema_boundary_config_and_claim_tampering_rejected(self):
        for action in ('range', 'config', 'extra', 'claim', 'type'):
            plan = copy.deepcopy(self.plan)
            if action == 'range': plan['ranges'][0]['end_index_exclusive'] += 1
            if action == 'config': plan['stress_config']['long_window'] = 6
            if action == 'extra': plan['extra'] = 1
            if action == 'claim': plan['live_authorized'] = True
            if action == 'type': plan['dataset']['candles'] = True
            self.plan_path.write_text(json.dumps(plan))
            self.reject()

    def test_recreated_plan_does_not_make_data_unseen_or_change_exported_values(self):
        first = self.run_export()
        first_csv = (self.destination/'development.csv').read_bytes()
        lines = self.csv.read_text().splitlines()
        lines[-1] = lines[-1].replace('105.000', '106')
        self.csv.write_text('\n'.join(lines)+'\n')
        self.replan()
        second_destination = self.root/'second'
        second = self.run_export(second_destination)
        self.assertEqual(first_csv, (second_destination/'development.csv').read_bytes())
        self.assertNotEqual(first['original_dataset']['raw_sha256'], second['original_dataset']['raw_sha256'])
        self.assertEqual(second['out_of_sample_status'], 'NOT_ESTABLISHED_CALLER_ASSERTION_ONLY')
        self.assertFalse(second['authenticated_plan_publication_established'])

    def test_verifier_rejects_changed_missing_extra_and_symlinked_bundle_files(self):
        self.run_export()
        for name in export.NAMES:
            path = self.destination/name
            original = path.read_bytes()
            path.write_bytes(original+b' ')
            with self.assertRaises(ValueError): self.verify()
            path.unlink()
            with self.assertRaises(ValueError): self.verify()
            path.symlink_to(self.plan_path)
            with self.assertRaises(ValueError): self.verify()
            path.unlink(); path.write_bytes(original)
        extra = self.destination/'extra'
        extra.write_text('preserve')
        with self.assertRaises(ValueError): self.verify()
        self.assertEqual(extra.read_text(), 'preserve')

    def test_verifier_requires_matching_original_full_input_and_plan(self):
        self.run_export()
        self.csv.write_bytes(self.csv.read_bytes()+b'\n')
        with self.assertRaises(ValueError): self.verify()

    def test_existing_destinations_inputs_and_backups_never_overwritten(self):
        self.destination.mkdir()
        keep = self.destination/'keep.bak'; keep.write_text('keep')
        with patch.object(export, '_prepare') as prepare, self.assertRaises(ValueError):
            self.run_export()
        prepare.assert_not_called()
        self.assertEqual(keep.read_text(), 'keep')
        for path in (self.csv, self.plan_path):
            original = path.read_bytes()
            with self.assertRaises(ValueError): self.run_export(path)
            self.assertEqual(path.read_bytes(), original)

    def test_missing_parent_and_symlink_paths_rejected(self):
        with self.assertRaises(ValueError): self.run_export(self.root/'missing/bundle')
        self.assertFalse((self.root/'missing').exists())
        link = self.root/'linked.csv'; link.symlink_to(self.csv)
        with self.assertRaises(ValueError): export.export_development(link, self.plan_path, self.destination)
        directory = self.root/'linked'; directory.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError): self.run_export(directory/'bundle')
        self.assertFalse(self.destination.exists())

    def test_plan_and_csv_file_alias_rejected(self):
        with self.assertRaises(ValueError): export.export_development(self.csv, self.csv, self.destination)
        self.assertFalse(self.destination.exists())

    def test_source_or_input_change_before_receipt_cleans_owned_output(self):
        original = export._recheck
        calls = 0
        def changing(retained, sources):
            nonlocal calls
            calls += 1
            if calls == 2:
                with self.plan_path.open('ab') as stream: stream.write(b' ')
            return original(retained, sources)
        with patch.object(export, '_recheck', side_effect=changing): self.reject()

    def test_source_code_change_prevents_completion(self):
        sources = export._sources()
        with patch.object(export, '_sources', side_effect=[sources, sources,
                {**sources, 'development_export.py': '0'*64}]):
            self.reject()

    def test_exclusive_directory_race_preserves_other_writer(self):
        original = Path.mkdir
        target = self.destination
        def racing(path, *args, **kwargs):
            if path == target:
                original(path, *args, **kwargs)
                (path/'other').write_text('other writer')
                raise FileExistsError('Synthetic directory race')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'mkdir', new=racing), self.assertRaises(FileExistsError): self.run_export()
        self.assertEqual((target/'other').read_text(), 'other writer')

    def test_failed_write_removes_only_owned_files_and_directory(self):
        original = Path.open
        class Broken:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, raw):
                self.stream.write(raw[:10]); raise OSError('Synthetic write failure')
        def broken(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return Broken(stream) if path.name == 'dataset-plan.json' and args and args[0] == 'xb' else stream
        originals = {p:p.read_bytes() for p in (self.csv, self.plan_path)}
        with patch.object(Path, 'open', new=broken): self.reject()
        self.assertEqual(originals, {p:p.read_bytes() for p in originals})

    def test_failure_cleanup_preserves_unrelated_and_replacement_files(self):
        original = Path.open
        def broken(path, *args, **kwargs):
            if path.name == 'dataset-plan.json' and args and args[0] == 'xb':
                csv = self.destination/'development.csv'
                csv.rename(self.root/'moved-owned.csv')
                csv.write_bytes(b'replacement')
                (self.destination/'other').write_bytes(b'unrelated')
                raise OSError('Synthetic failure after replacement')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'open', new=broken), self.assertRaises(OSError): self.run_export()
        self.assertEqual((self.destination/'development.csv').read_bytes(), b'replacement')
        self.assertEqual((self.destination/'other').read_bytes(), b'unrelated')

    def test_bounds_and_strict_json_rejected_before_output(self):
        for name in ('MAX_PLAN_BYTES', 'MAX_RECEIPT_BYTES', 'MAX_BYTES'):
            with patch.object(export, name, 1): self.reject()
        for raw in ('[]', '{bad', '{"x":NaN}', '{"x":1,"x":2}'):
            self.plan_path.write_text(raw); self.reject()

    def test_hostile_decimal_context_does_not_change_export_bytes(self):
        first = self.run_export()
        second = self.root/'second'
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True
            self.assertEqual(self.run_export(second), first)
        for name in export.NAMES:
            self.assertEqual((self.destination/name).read_bytes(), (second/name).read_bytes())

    def test_binance_microseconds_export_to_exact_milliseconds(self):
        rows = []
        for bar in self.dataset.candles:
            row = [bar.timestamp_ms*1000, bar.open, bar.high, bar.low, bar.close, bar.volume,
                   (bar.timestamp_ms+60000)*1000-1, 0, 0, 0, 0, 0]
            rows.append(','.join(map(str, row)))
        self.csv.write_text('\n'.join(rows)+'\n')
        self.options.update(input_format='binance-spot', timestamp_unit='us')
        self.replan()
        receipt = self.run_export()
        converted = load_candles(self.destination/'development.csv', **{**self.options,
            'input_format':'canonical', 'timestamp_unit':'ms'})
        self.assertEqual(converted.candles, self.dataset.candles[:12])
        self.assertEqual(receipt['original_dataset']['timestamp_unit'], 'us')
        self.assertEqual(receipt['exported_dataset']['timestamp_unit'], 'ms')

    def test_real_fixture_development_only_smoke(self):
        self.csv = ROOT/'examples/a007/BTCUSDT-1h-2024-01-01.csv'
        self.options = dict(symbol='BTCUSDT', source='EXISTING REAL FIXTURE; ALREADY SEEN; SMOKE ONLY',
            interval_ms=3600000, as_of_ms=1704153600000, input_format='binance-spot')
        self.plan = self.replan()
        receipt = self.run_export()
        self.assertEqual(receipt['exported_dataset']['candles'], 12)
        self.assertEqual(receipt['reserved_range']['candles'], 12)
        self.assertEqual(receipt, self.verify())
        self.assertFalse(receipt['reserved_performance_evaluated_by_this_operation'])

    def test_cli_determinism_verification_and_failure(self):
        def process(command, destination):
            return subprocess.run([sys.executable, '-m', 'ariyan_trading.development_export', command,
                '--csv',str(self.csv),'--plan',str(self.plan_path),'--destination',str(destination)],
                cwd=self.root, env={**os.environ,'PYTHONPATH':str(ROOT/'app')}, capture_output=True,text=True)
        first = process('export', self.destination)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn('Reserved candles exported: 0', first.stdout)
        self.assertEqual(process('verify', self.destination).returncode, 0)
        second = self.root/'second'
        self.assertEqual(process('export', second).returncode, 0)
        for name in export.NAMES:
            self.assertEqual((self.destination/name).read_bytes(), (second/name).read_bytes())
        self.assertEqual(process('export', self.destination).returncode, 2)
        self.plan_path.write_text('{bad')
        with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as raised:
            export.main(['export','--csv',str(self.csv),'--plan',str(self.plan_path),
                         '--destination',str(self.root/'bad')])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse((self.root/'bad').exists())


if __name__ == '__main__':
    unittest.main()
