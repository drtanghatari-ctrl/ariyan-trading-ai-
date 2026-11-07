"""Copied-review consistency and explicit non-authentication boundaries."""
import copy
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import unittest
from decimal import Inexact, localcontext
from pathlib import Path
from unittest.mock import patch

import test_development_review_a024 as fixtures
from ariyan_trading import review_inspector as inspector

ROOT=Path(__file__).resolve().parents[1]


class ReviewInspectorA025Tests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.DevelopmentReviewA024Tests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.root=fixture.root
        fixture.run_review();self.review=fixture.destination

    def inspect(self): return inspector.inspect_review(self.review)

    def read(self,name): return json.loads((self.review/name).read_bytes())

    def write(self,name,value):
        (self.review/name).write_bytes(inspector.exports._encoded(value))

    def rehash_file(self,name):
        complete=self.read('COMPLETE.json')
        complete['files_sha256'][name]=hashlib.sha256((self.review/name).read_bytes()).hexdigest()
        self.write('COMPLETE.json',complete)

    def reject(self):
        with self.assertRaises((ValueError,OSError,TypeError,KeyError,IndexError)):self.inspect()

    def test_complete_folder_inspected_without_writes_replay_or_original_reads(self):
        original={p:p.read_bytes() for p in self.review.rglob('*') if p.is_file()}
        self.fixture.fixture.csv.unlink();self.fixture.fixture.plan_path.unlink()
        with (patch.object(inspector.exports,'verify_development_export',side_effect=AssertionError('No originals')),
              patch.object(inspector.batch,'run_session_replay',side_effect=AssertionError('No replay'))):
            result=self.inspect()
        self.assertEqual(result['job_count'],2)
        self.assertTrue(result['artifact_hashes_match'])
        self.assertEqual(original,{p:p.read_bytes() for p in original})
        for name in ('original_full_inputs_reopened','original_full_inputs_independently_verified',
                     'replay_rerun','source_authenticity_established','live_authorized'):
            self.assertIs(result[name],False)

    def test_moved_review_is_portable(self):
        expected=self.inspect()
        moved=self.root/'moved';shutil.copytree(self.review,moved)
        self.assertEqual(inspector.inspect_review(moved),expected)

    def test_missing_or_partial_completion_rejected(self):
        path=self.review/'COMPLETE.json';raw=path.read_bytes()
        path.unlink();self.reject()
        path.write_bytes(raw[:50]);self.reject()

    def test_each_changed_artifact_rejected(self):
        for name in ('BATCH.json','REVIEW.html','batch-request.json','PLAN_BINDINGS.json',
                     'inputs/job-00/export/development.csv','inputs/job-00/export/EXPORT.json'):
            path=self.review/name;raw=path.read_bytes()
            path.write_bytes(raw+b' ');self.reject();path.write_bytes(raw)

    def test_unsafe_manifest_reference_rejected_even_with_updated_file_hash(self):
        manifest=self.read('batch-request.json')
        manifest['jobs'][0]['csv']=str(self.fixture.fixture.csv)
        self.write('batch-request.json',manifest);self.rehash_file('batch-request.json');self.reject()

    def test_unsafe_hash_map_and_unknown_files_rejected(self):
        complete=self.read('COMPLETE.json');complete['files_sha256']['../outside']='0'*64
        self.write('COMPLETE.json',complete);self.reject()
        del complete['files_sha256']['../outside'];self.write('COMPLETE.json',complete)
        (self.review/'other').write_text('preserve');self.reject()
        self.assertEqual((self.review/'other').read_text(),'preserve')

    def test_missing_symlinked_and_nonregular_artifacts_rejected(self):
        path=self.review/'REVIEW.html';raw=path.read_bytes();path.unlink();self.reject()
        path.symlink_to(self.fixture.request_path);self.reject();path.unlink()
        path.mkdir();self.reject();path.rmdir();path.write_bytes(raw)
        linked=self.root/'linked';linked.symlink_to(self.review,target_is_directory=True)
        with self.assertRaises(ValueError):inspector.inspect_review(linked)

    def test_rehashed_summary_inconsistency_still_rejected(self):
        complete=self.read('COMPLETE.json');complete['summary_table'][0]['filled_orders']+=1
        self.write('COMPLETE.json',complete);self.reject()

    def test_rehashed_binding_inconsistency_rejected(self):
        evidence=self.read('PLAN_BINDINGS.json');evidence['jobs'][0]['development_csv_sha256']='0'*64
        self.write('PLAN_BINDINGS.json',evidence);self.rehash_file('PLAN_BINDINGS.json');self.reject()

    def test_rehashed_copied_intake_change_rejected(self):
        path='inputs/job-00/export/development.csv'
        data=(self.review/path).read_text().replace(',13,13,13,13,',',14,14,14,14,')
        (self.review/path).write_text(data);self.rehash_file(path);self.reject()

    def test_rehashed_html_change_rejected(self):
        path=self.review/'REVIEW.html';path.write_bytes(path.read_bytes()+b'<!-- changed -->')
        self.rehash_file('REVIEW.html');self.reject()

    def test_recorded_authority_and_schema_claims_rejected(self):
        original=self.read('COMPLETE.json')
        for name,value in (('live_authorized',True),('job_count',True),('extra',1),('version','future')):
            complete=copy.deepcopy(original);complete[name]=value
            self.write('COMPLETE.json',complete);self.reject()

    def test_nonfinite_duplicate_json_and_node_byte_bounds(self):
        path=self.review/'COMPLETE.json';raw=path.read_bytes()
        for text in ('[]','{"x":NaN}','{"version":1,"version":2}'):
            path.write_text(text);self.reject()
        path.write_bytes(raw)
        with patch.object(inspector,'MAX_NODES',1):self.reject()
        with patch.object(inspector.workflow,'MAX_BUNDLE_BYTES',1):self.reject()
        with patch.object(inspector.batch,'MAX_TOTAL_INPUT_BYTES',1):self.reject()
        with patch.object(inspector.batch,'MAX_TOTAL_GRID_SLOTS',1):self.reject()

    def test_input_change_midinspection_is_detected(self):
        original=inspector.view.render_report
        def changed(report):
            result=original(report)
            with (self.review/'REVIEW_REQUEST.json').open('ab') as stream:stream.write(b' ')
            return result
        with patch.object(inspector.view,'render_report',side_effect=changed):self.reject()

    def test_new_file_midinspection_is_detected_and_preserved(self):
        original=inspector.view.render_report
        def changed(report):
            result=original(report);(self.review/'other').write_text('preserve');return result
        with patch.object(inspector.view,'render_report',side_effect=changed):self.reject()
        self.assertEqual((self.review/'other').read_text(),'preserve')

    def test_changed_manifest_cannot_redirect_intake_to_originals(self):
        original_check=inspector.view.validate_display_report
        original_load=inspector.batch.load_session_candles
        def changed(report):
            result=original_check(report)
            manifest=self.read('batch-request.json')
            manifest['jobs'][0]['csv']=str(self.fixture.fixture.csv)
            self.write('batch-request.json',manifest)
            return result
        def guarded(path,**kwargs):
            self.assertTrue(Path(path).is_relative_to(self.review))
            return original_load(path,**kwargs)
        with (patch.object(inspector.view,'validate_display_report',side_effect=changed),
              patch.object(inspector.batch,'load_session_candles',side_effect=guarded)):
            self.reject()

    def test_consistent_recreated_records_are_not_authenticated(self):
        # No digest is a signature: an unsigned completion record can be recreated.
        complete=self.read('COMPLETE.json')
        complete['source_file_sha256']['development_review.py']='0'*64
        self.write('COMPLETE.json',complete)
        result=self.inspect()
        self.assertEqual(result['status'],'CONSISTENT_SAVED_ARTIFACTS_NOT_AUTHENTICATED')
        self.assertFalse(result['source_authenticity_established'])

    def test_decimal_context_isolation(self):
        expected=self.inspect()
        with localcontext() as context:
            context.prec=2;context.traps[Inexact]=True
            self.assertEqual(self.inspect(),expected)

    def test_fresh_process_deterministic_json_and_cli_rejection(self):
        results=[]
        for _ in range(2):
            run=subprocess.run([sys.executable,'-m','ariyan_trading.review_inspector','--review',str(self.review)],
                cwd=self.root,env={**os.environ,'PYTHONPATH':str(ROOT/'app')},capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);results.append(run.stdout)
            self.assertEqual(json.loads(run.stdout),self.inspect())
        self.assertEqual(*results)
        (self.review/'COMPLETE.json').unlink()
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as raised:
            inspector.main(['--review',str(self.review)])
        self.assertEqual(raised.exception.code,2)


if __name__=='__main__':unittest.main()
