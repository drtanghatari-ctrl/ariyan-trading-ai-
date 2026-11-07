"""Saved-report consistency, offline HTML escaping, file safety and plotting tests."""
import copy
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from decimal import Inexact, localcontext
from html.parser import HTMLParser
from unittest.mock import patch

import test_replay_batch_a021 as fixtures
from ariyan_trading import replay_view as view


class Elements(HTMLParser):
    def __init__(self):
        super().__init__(); self.elements = []
    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class ReplayViewA022Tests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.ReplayBatchA021Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.root
        self.report = fixture.run_batch()
        self.source = fixture.output
        self.output = self.root/'review.html'

    def rehash(self, report=None):
        report = self.report if report is None else report
        body = {k:v for k,v in report.items() if k != 'batch_sha256'}
        report['batch_sha256'] = hashlib.sha256(view.batch.VERSION.encode()+b'\0'+view.batch.files._canonical(body)).hexdigest()

    def save(self):
        self.source.write_text(json.dumps(self.report))

    def reject(self):
        self.save()
        with self.assertRaises((ValueError, TypeError, KeyError)):
            view.write_view(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_saved_report_renders_without_replay_network_or_input_reopening(self):
        before = self.source.read_bytes()
        with patch.object(view.batch, 'run_session_replay', side_effect=AssertionError('No replay')):
            # Original metadata/CSV are unnecessary to read a previously saved report.
            for path in self.root.glob('*/*'):
                if path.is_file(): path.unlink()
            self.assertEqual(view.write_view(self.source, self.output), 2)
        raw = self.output.read_text()
        self.assertIn('stock', raw); self.assertIn('crypto', raw)
        self.assertIn('USD', raw); self.assertIn('USDT', raw)
        self.assertIn('separate simulated accounts', raw)
        self.assertEqual(self.source.read_bytes(), before)

    def test_unsigned_hash_mismatch_rejected(self):
        self.report['jobs'][0]['replay']['summary']['return_pct'] = '100'
        self.reject()

    def test_rehashed_summary_table_mismatch_rejected(self):
        self.report['summary_table'][0]['filled_orders'] += 1
        self.rehash(); self.reject()

    def test_rehashed_summary_arithmetic_mismatch_rejected(self):
        original = copy.deepcopy(self.report)
        for name in ('return_pct', 'net_marked_pnl', 'max_observed_close_drawdown_pct', 'final_cash', 'total_fees'):
            self.report = copy.deepcopy(original)
            self.report['jobs'][0]['replay']['summary'][name] = '999'
            self.rehash(); self.reject()

    def test_rehashed_curve_order_drawdown_and_nonfinite_values_rejected(self):
        original = copy.deepcopy(self.report)
        for field, value in (('close_timestamp_ms', True), ('marked_equity', 'NaN'),
                             ('marked_equity', '1e999'), ('close_drawdown_pct', '99'), ('cash', '-1')):
            self.report = copy.deepcopy(original)
            self.report['jobs'][0]['replay']['equity_curve'][1][field] = value
            self.rehash(); self.reject()
        self.report = copy.deepcopy(original)
        curve = self.report['jobs'][0]['replay']['equity_curve']
        curve[1]['close_timestamp_ms'] = curve[0]['close_timestamp_ms']
        self.rehash(); self.reject()

    def test_authority_claims_rejected_even_when_rehashed(self):
        original = copy.deepcopy(self.report)
        for area, field in (('batch','live_authorized'), ('batch','portfolio_aggregation_performed'),
                ('replay','strategy_promoted'), ('replay','production_risk_approval_established'),
                ('intake','calendar_independently_verified')):
            self.report = copy.deepcopy(original)
            target = self.report if area == 'batch' else self.report['jobs'][0]['replay']
            if area == 'intake': target = target['intake']
            target[field] = True
            self.rehash(); self.reject()

    def test_job_schema_identity_types_and_counts_rejected(self):
        original = copy.deepcopy(self.report)
        for action in ('unknown', 'identity', 'count', 'config', 'duplicates'):
            self.report = copy.deepcopy(original)
            if action == 'unknown': self.report['unknown'] = 1
            if action == 'identity': self.report['jobs'][0]['instrument_identity']['venue'] = 'OTHER'
            if action == 'count': self.report['job_count'] = True
            if action == 'config': self.report['jobs'][0]['replay']['config']['short_window'] = True
            if action == 'duplicates': self.report['jobs'][1]['job_id'] = self.report['jobs'][0]['job_id']
            self.rehash(); self.reject()

    def test_labels_limitations_and_json_details_are_escaped(self):
        attack = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        replay = self.report['jobs'][0]['replay']
        replay['intake']['instrument']['display_symbol'] = attack
        replay['intake']['source']['label'] = attack
        replay['limitations'].append(attack)
        self.report['limitations'].append(attack)
        self.rehash()
        raw = view.render_report(self.report).decode()
        self.assertIn('&lt;script&gt;', raw)
        self.assertNotIn('<script>', raw)
        parser = Elements(); parser.feed(raw)
        for tag, attributes in parser.elements:
            self.assertNotIn(tag, ('script', 'iframe', 'img', 'link', 'object', 'form', 'base'))
            self.assertFalse(any(k.startswith('on') for k in attributes))

    def test_html_has_no_remote_assets_or_active_controls(self):
        raw = view.render_report(self.report).decode()
        parser = Elements(); parser.feed(raw)
        self.assertIn("default-src 'none'", raw)
        self.assertNotIn('fetch(', raw)
        for _, attrs in parser.elements:
            self.assertNotIn('src', attrs)
            self.assertNotIn('href', attrs)
        self.assertIn('name="viewport"', raw)
        self.assertIn('max-width:620px', raw)
        self.assertIn('Signals and fills were not rerun', raw)

    def test_full_curve_points_and_native_elapsed_times_preserved(self):
        replay = self.report['jobs'][0]['replay']
        raw = view._chart(replay, 0)
        points = re.search('points="([^"]+)"', raw).group(1).split()
        self.assertEqual(len(points), len(replay['equity_curve'])+1)
        self.assertEqual(points[0].split(',')[0], '32.000')
        self.assertEqual(points[-1].split(',')[0], '608.000')
        grid = replay['intake']['session_assessment']['grid']
        grid['end_exclusive_ms'] *= 2
        stretched = re.search('points="([^"]+)"', view._chart(replay, 0)).group(1).split()
        self.assertEqual(stretched[-1].split(',')[0], '320.000')

    def test_flat_and_tiny_equity_charts_have_finite_coordinates(self):
        replay = copy.deepcopy(self.report['jobs'][0]['replay'])
        for amount in ('1000', '0.000000000001'):
            replay['summary']['opening_cash'] = amount
            for point in replay['equity_curve']: point['marked_equity'] = amount
            raw = view._chart(replay, 0)
            self.assertNotIn('NaN', raw); self.assertNotIn('Infinity', raw)
            self.assertTrue(re.search('points="[0-9., ]+"', raw))

    def test_halt_and_unliquidated_stale_marks_are_visible(self):
        self.fixture.request['jobs'][0]['config']['max_close_drawdown_pct'] = '0.01'
        self.fixture.save()
        report = self.fixture.run_batch(self.root/'halted.json')
        raw = view.render_report(report).decode()
        self.assertIn('HALTED IN SIMULATION', raw)
        self.assertIn('Terminal equity excludes forced liquidation', raw)
        # Chart/display policy is explicitly separate from valuation computation.
        replay = report['jobs'][1]['replay']
        grid = replay['intake']['session_assessment']['grid']
        grid['end_exclusive_ms'] += grid['interval_ms']
        replay['summary']['last_mark_precedes_requested_end'] = True
        report['summary_table'][1]['last_mark_precedes_requested_end'] = True
        self.rehash(report)
        self.assertIn('Last mark precedes requested end', view.render_report(report).decode())

    def test_deterministic_fresh_process_rendering(self):
        outputs = []
        for name in ('first.html', 'second.html'):
            destination = self.root/name
            result = subprocess.run([sys.executable, '-m', 'ariyan_trading.replay_view',
                '--report', str(self.source), '--output', str(destination)], cwd=self.root,
                env={**os.environ, 'PYTHONPATH':str(fixtures.ROOT/'app')}, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('NO REPLAY', result.stdout)
            outputs.append(destination.read_bytes())
        self.assertEqual(*outputs)

    def test_hostile_decimal_context_does_not_change_html(self):
        expected = view.render_report(self.report)
        with localcontext() as context:
            context.prec = 2; context.traps[Inexact] = True
            self.assertEqual(view.render_report(self.report), expected)

    def test_existing_output_and_input_never_overwritten(self):
        before = self.source.read_bytes()
        with self.assertRaises(ValueError): view.write_view(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)
        self.output.write_bytes(b'keep')
        with self.assertRaises(ValueError): view.write_view(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'keep')

    def test_symlinks_and_missing_parent_rejected(self):
        linked = self.root/'link.json'; linked.symlink_to(self.source)
        with self.assertRaises(ValueError): view.write_view(linked, self.output)
        linked_output = self.root/'link.html'; linked_output.symlink_to(self.source)
        with self.assertRaises(ValueError): view.write_view(self.source, linked_output)
        with self.assertRaises(ValueError): view.write_view(self.source, self.root/'absent/view.html')
        self.assertFalse((self.root/'absent').exists())

    def test_input_and_html_byte_limits_prevent_output(self):
        with patch.object(view.batch, 'MAX_REPORT_BYTES', 1), self.assertRaises(ValueError):
            view.write_view(self.source, self.output)
        with patch.object(view, 'MAX_HTML_BYTES', 1), self.assertRaises(ValueError):
            view.write_view(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_input_change_during_render_prevents_output(self):
        original = view.render_report
        def change(report):
            result = original(report)
            with self.source.open('ab') as stream: stream.write(b' ')
            return result
        with patch.object(view, 'render_report', side_effect=change), self.assertRaises(ValueError):
            view.write_view(self.source, self.output)
        self.assertFalse(self.output.exists())

    def test_exclusive_creation_race_preserves_other_file(self):
        original = view.batch.files._write
        def racing(path, raw):
            path.write_bytes(b'other writer')
            return original(path, raw)
        with patch.object(view.batch.files, '_write', side_effect=racing), self.assertRaises(FileExistsError):
            view.write_view(self.source, self.output)
        self.assertEqual(self.output.read_bytes(), b'other writer')

    def test_write_failure_removes_only_owned_partial_file(self):
        from pathlib import Path
        original = Path.open
        target = self.output
        class Broken:
            def __init__(self, stream): self.stream = stream
            def __enter__(self): return self
            def __exit__(self, *args): self.stream.close()
            def write(self, raw):
                self.stream.write(raw[:10]); raise OSError('Synthetic interruption')
        def broken(path, *args, **kwargs):
            stream = original(path, *args, **kwargs)
            return Broken(stream) if path == target and args and args[0] == 'xb' else stream
        with patch.object(Path, 'open', new=broken), self.assertRaises(OSError):
            view.write_view(self.source, self.output)
        self.assertFalse(self.output.exists()); self.assertTrue(self.source.exists())

    def test_invalid_json_duplicate_keys_and_cli_errors(self):
        for raw in ('[]', '{"x":NaN}', '{"version":1,"version":2}', '{bad'):
            self.source.write_text(raw)
            with patch('sys.stderr', new=io.StringIO()), self.assertRaises(SystemExit) as raised:
                view.main(['--report',str(self.source),'--output',str(self.output)])
            self.assertEqual(raised.exception.code, 2)
            self.assertFalse(self.output.exists())

    def test_report_can_be_rehashed_without_establishing_authenticity(self):
        self.report['limitations'].append('Changed by caller; unsigned report remains untrusted.')
        self.rehash()
        raw = view.render_report(self.report).decode()
        self.assertIn('A modified report can be rehashed', raw)
        self.assertIn('Changed by caller', raw)

    def test_real_btc_smoke_report_renders_with_explicit_source_label(self):
        self.fixture.output.unlink()
        self.fixture.test_real_btc_fixture_base_and_stress_smoke_only()
        report = json.loads(self.fixture.output.read_bytes())
        raw = view.render_report(report).decode()
        self.assertIn('EXISTING REAL FIXTURE; SMOKE ONLY', raw)
        self.assertEqual(raw.count('<svg '), 2)
        self.assertIn('Strategy not validated', raw)


if __name__ == '__main__':
    unittest.main()
