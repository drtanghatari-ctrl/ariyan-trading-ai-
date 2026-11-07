"""Synthetic end-to-end development export, plan binding, batch and HTML workflow."""
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest
from dataclasses import asdict, replace
from decimal import Inexact, localcontext
from pathlib import Path
from unittest.mock import patch

import test_development_export_a023 as fixtures
from test_session_replay_a017 import series as terms_fixture, config as configuration
from ariyan_trading import development_review as review
from ariyan_trading.sessions import SessionWindow
from ariyan_trading.instruments import AssetClass, ProductType, SettlementType


class DevelopmentReviewA024Tests(unittest.TestCase):
    def setUp(self):
        fixture = fixtures.DevelopmentExportA023Tests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture; self.root = fixture.root
        prices = (10,11,12,13,12,11,10,9,10,11,12,13) + (100,)*13
        fixture.csv.write_text(','.join(fixtures.HEADER)+'\n'+''.join(
            f'{i*60000},{p},{p},{p},{p},10\n' for i,p in enumerate(prices)))
        fixture.plan = fixture.replan(); self.receipt = fixture.run_export()
        template = terms_fixture(); end = 12*60000
        self.spec = replace(template.spec, effective_until_ms=end, observed_at_ms=end)
        schedule = replace(template.schedule, coverage_end_ms=end,
                           windows=(SessionWindow(0,end,'SYNTHETIC'),), observed_at_ms=end)
        self.instrument = self.root/'instrument.json'; self.instrument.write_text(json.dumps(self.spec.to_record()))
        self.schedule = self.root/'schedule.json'; self.schedule.write_text(json.dumps(schedule.to_record()))
        self.request_path = self.root/'request.json'; self.destination = self.root/'review'
        self.request = {'version':review.REQUEST_VERSION,
            'experiment_note':'SYNTHETIC TEST ONLY: explicit A017 execution/risk revision, no strategy promotion.',
            'jobs':[self.job('base'), self.job('stress')]}
        self.save()

    def job(self, scenario):
        recorded = self.receipt['config' if scenario == 'base' else 'stress_config']
        config = {**asdict(configuration()), **recorded}
        return {'job_id':'synthetic-'+scenario, 'original_csv':self.fixture.csv.name,
            'plan':self.fixture.plan_path.name,'export_directory':self.fixture.destination.name,
            'instrument':self.instrument.name,'schedule':self.schedule.name,'scenario':scenario,
            'mapping_source':'SYNTHETIC CALLER MAPPING','volume_unit':'SHARE',
            'price_basis':'RAW_UNADJUSTED_SINGLE_INSTRUMENT','config':config}

    def save(self): self.request_path.write_text(json.dumps(self.request, sort_keys=True))

    def run_review(self, destination=None):
        return review.run_development_review(self.request_path, destination or self.destination)

    def reject(self):
        with self.assertRaises((ValueError,OSError,TypeError,KeyError)):
            self.run_review()
        self.assertFalse(self.destination.exists())

    def test_complete_workflow_matches_direct_engine_and_contains_bound_inputs(self):
        before = {p:p.read_bytes() for p in (self.fixture.csv,self.fixture.plan_path,self.instrument,self.schedule)}
        complete = self.run_review()
        report = json.loads((self.destination/'BATCH.json').read_bytes())
        _, _, jobs = review.batch._prepare(self.destination/'batch-request.json')
        for index, (_,series,config,_) in enumerate(jobs):
            self.assertEqual(report['jobs'][index]['replay'], review.batch.run_session_replay(series,config))
        self.assertEqual(complete['summary_table'],report['summary_table'])
        self.assertIn('separate simulated accounts',(self.destination/'REVIEW.html').read_text())
        for relative,digest in complete['files_sha256'].items():
            self.assertEqual(hashlib.sha256((self.destination/relative).read_bytes()).hexdigest(),digest)
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        bindings = json.loads((self.destination/'PLAN_BINDINGS.json').read_bytes())
        self.assertEqual(bindings['experiment_note'],self.request['experiment_note'])
        self.assertEqual([b['scenario'] for b in bindings['jobs']],['base','stress'])
        self.assertEqual(bindings['jobs'][0]['development_csv_sha256'],self.receipt['exported_dataset']['raw_sha256'])

    def test_only_verified_development_bars_reach_engine(self):
        original = review.batch.run_session_replay; seen=[]
        def checked(series, config):
            seen.append(series)
            self.assertEqual(len(series.candles),12)
            self.assertTrue(all(b.timestamp_ms < self.receipt['reserved_range']['first_open_ms'] for b in series.candles))
            self.assertTrue(all(b.close < 100 for b in series.candles))
            return original(series,config)
        with patch.object(review.batch,'run_session_replay',side_effect=checked): self.run_review()
        self.assertEqual(len(seen),2)
        for path in self.destination.rglob('*.csv'):
            self.assertEqual(len(path.read_text().splitlines()),13)

    def test_shared_plan_parameters_cannot_be_silently_changed(self):
        original = copy.deepcopy(self.request)
        for field,value in (('fee_bps','0'),('slippage_bps','0'),('short_window',2),
                            ('opening_cash','100'),('max_position_fraction','1')):
            self.request = copy.deepcopy(original)
            self.request['jobs'][1]['config'][field] = value; self.save()
            with patch.object(review.batch,'run_session_replay') as engine:
                self.reject(); engine.assert_not_called()

    def test_extra_cash_risk_settings_are_explicit_and_preserved(self):
        self.request['jobs'][0]['config']['max_close_drawdown_pct']='0.01'
        self.request['experiment_note']='SYNTHETIC ONLY <script>alert("bad")</script>'
        self.save(); self.run_review()
        report=json.loads((self.destination/'BATCH.json').read_bytes())
        self.assertEqual(report['jobs'][0]['replay']['config']['max_close_drawdown_pct'],'0.01')
        binding=json.loads((self.destination/'PLAN_BINDINGS.json').read_bytes())['jobs'][0]
        self.assertFalse(binding['a007_execution_equivalence_established'])
        html=(self.destination/'REVIEW.html').read_text()
        self.assertIn('Caller experiment note (unverified)',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)

    def test_all_exports_verified_before_any_replay(self):
        self.request['jobs'][1]['export_directory']='missing'; self.save()
        with patch.object(review.batch,'run_session_replay') as engine:
            self.reject(); engine.assert_not_called()

    def test_changed_export_or_original_rejected(self):
        export_csv=self.fixture.destination/'development.csv'; before=export_csv.read_bytes()
        export_csv.write_bytes(before+b' '); self.reject(); export_csv.write_bytes(before)
        self.fixture.csv.write_bytes(self.fixture.csv.read_bytes()+b'\n'); self.reject()

    def test_strict_schema_note_scenario_duplicate_ids_and_types(self):
        original=copy.deepcopy(self.request)
        for action in ('extra','version','note','empty','duplicate','scenario','config','path','claim'):
            self.request=copy.deepcopy(original)
            if action=='extra': self.request['extra']=1
            if action=='version': self.request['version']='future'
            if action=='note': self.request['experiment_note']=' '
            if action=='empty': self.request['jobs']=[]
            if action=='duplicate': self.request['jobs'][1]['job_id']=self.request['jobs'][0]['job_id']
            if action=='scenario': self.request['jobs'][0]['scenario']='reserved'
            if action=='config': self.request['jobs'][0]['config']['short_window']=True
            if action=='path': self.request['jobs'][0]['plan']=False
            if action=='claim': self.request['jobs'][0]['live_authorized']=True
            self.save(); self.reject()

    def test_bad_instrument_or_schedule_never_leaves_complete_review(self):
        original=self.instrument.read_bytes()
        self.instrument.write_text('{}'); self.reject(); self.instrument.write_bytes(original)
        self.schedule.write_text('[]'); self.reject()

    def test_existing_destination_is_preserved_before_preparation(self):
        self.destination.mkdir(); keep=self.destination/'keep.bak'; keep.write_text('keep')
        with patch.object(review,'_prepare') as prepare,self.assertRaises(ValueError): self.run_review()
        prepare.assert_not_called(); self.assertEqual(keep.read_text(),'keep')

    def test_missing_parent_and_symlink_inputs_rejected(self):
        with self.assertRaises(ValueError): self.run_review(self.root/'absent/review')
        self.assertFalse((self.root/'absent').exists())
        linked=self.root/'linked-request.json'; linked.symlink_to(self.request_path)
        with self.assertRaises(ValueError): review.run_development_review(linked,self.destination)
        linked=self.root/'linked-export'; linked.symlink_to(self.fixture.destination,target_is_directory=True)
        self.request['jobs'][0]['export_directory']=linked.name; self.save(); self.reject()

    def test_input_mutation_after_replay_aborts_completion(self):
        original=review.batch.run_batch
        def changed(*args):
            report=original(*args)
            with self.fixture.csv.open('ab') as stream: stream.write(b' ')
            return report
        with patch.object(review.batch,'run_batch',side_effect=changed): self.reject()

    def test_staged_input_mutation_detected_even_if_a021_accepts_it(self):
        original=review.batch.run_batch
        def changed(manifest, output):
            path=self.destination/'inputs/job-00/export/development.csv'
            path.write_text(path.read_text().replace(',13,13,13,13,',',14,14,14,14,'))
            return original(manifest,output)
        with patch.object(review.batch,'run_batch',side_effect=changed): self.reject()

    def test_implementation_change_aborts_completion(self):
        sources=review._sources()
        with patch.object(review,'_sources',side_effect=[sources,sources,{**sources,'development_review.py':'0'*64}]):
            self.reject()

    def test_viewer_failure_removes_owned_batch_and_inputs(self):
        with patch.object(review.view,'render_report',side_effect=ValueError('Synthetic viewer failure')):
            self.reject()
        self.assertTrue(self.fixture.destination.exists())

    def test_completed_batch_file_tampering_detected(self):
        original=review.batch.run_batch
        def changed(manifest, output):
            result=original(manifest,output)
            output.write_bytes(output.read_bytes()+b' ')
            return result
        with patch.object(review.batch,'run_batch',side_effect=changed): self.reject()

    def test_completion_write_failure_cleans_owned_partial_directory(self):
        original=Path.open
        class Broken:
            def __init__(self, stream): self.stream=stream
            def __enter__(self): return self
            def __exit__(self,*args): self.stream.close()
            def write(self,raw):
                self.stream.write(raw[:10]); raise OSError('Synthetic completion failure')
        def broken(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return Broken(stream) if path.name=='COMPLETE.json' and args and args[0]=='xb' else stream
        with patch.object(Path,'open',new=broken): self.reject()

    def test_failure_preserves_unrelated_concurrent_file(self):
        def changed(*args):
            (self.destination/'other').write_text('unrelated')
            raise ValueError('Synthetic batch failure')
        with patch.object(review.batch,'run_batch',side_effect=changed),self.assertRaises(ValueError): self.run_review()
        self.assertEqual((self.destination/'other').read_text(),'unrelated')
        self.assertFalse((self.destination/'COMPLETE.json').exists())

    def test_directory_creation_race_preserves_other_writer(self):
        original=Path.mkdir; target=self.destination
        def racing(path,*args,**kwargs):
            if path==target:
                original(path,*args,**kwargs); (path/'other').write_text('other')
                raise FileExistsError('Synthetic directory race')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',new=racing),self.assertRaises(FileExistsError): self.run_review()
        self.assertEqual((target/'other').read_text(),'other')

    def test_byte_bounds_and_malformed_json_prevent_completion(self):
        for field in ('MAX_INPUT_BYTES','MAX_BUNDLE_BYTES','MAX_COMPLETE_BYTES'):
            with patch.object(review,field,1): self.reject()
        for raw in ('[]','{bad','{"x":NaN}','{"version":1,"version":2}'):
            self.request_path.write_text(raw); self.reject()

    def test_context_isolation_no_shared_portfolio_and_no_authority(self):
        first=self.run_review(); second=self.root/'second'
        with localcontext() as context:
            context.prec=2; context.traps[Inexact]=True
            self.assertEqual(first,self.run_review(second))
        for field in ('strategy_promoted','live_authorized','global_reservation_access_control_established',
                      'reserved_performance_evaluated_by_this_operation'):
            self.assertIs(first[field],False)
        self.assertEqual(first['job_count'],2)
        self.assertNotIn('portfolio_return_pct',first)

    def test_fresh_process_determinism_cli_success_and_rejection(self):
        destinations=[self.destination,self.root/'second']
        for destination in destinations:
            result=subprocess.run([sys.executable,'-m','ariyan_trading.development_review',
                '--request',str(self.request_path),'--destination',str(destination)],cwd=self.root,
                env={**os.environ,'PYTHONPATH':str(fixtures.ROOT/'app')},capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('NO STRATEGY PROMOTION',result.stdout)
        for path in self.destination.rglob('*'):
            if path.is_file(): self.assertEqual(path.read_bytes(),(destinations[1]/path.relative_to(self.destination)).read_bytes())
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as raised:
            review.main(['--request',str(self.request_path),'--destination',str(self.destination)])
        self.assertEqual(raised.exception.code,2)

    def test_retained_real_btc_development_smoke_end_to_end(self):
        fixture=self.fixture
        fixture.csv=fixtures.ROOT/'examples/a007/BTCUSDT-1h-2024-01-01.csv'
        fixture.options=dict(symbol='BTCUSDT',source='EXISTING REAL FIXTURE; ALREADY SEEN; SMOKE ONLY',
            interval_ms=3600000,as_of_ms=1704153600000,input_format='binance-spot')
        fixture.plan=fixture.replan()
        for path in fixture.destination.iterdir(): path.unlink()
        fixture.destination.rmdir()
        self.receipt=fixture.run_export()
        start=self.receipt['exported_dataset']['first_open_ms']; end=self.receipt['exported_dataset']['last_close_ms']
        template=terms_fixture()
        spec=replace(template.spec,asset_class=AssetClass.CRYPTO,product=ProductType.SPOT,
            quote_currency='USDT',settlement_currency='USDT',quantity_unit='BTC',price_unit='USDT_PER_BTC',
            price_step='0.00000001',quantity_step='0.00000001',minimum_quantity='0.00000001',
            corporate_action_reference='NOT_APPLICABLE',settlement_type=SettlementType.ASSET_DELIVERY,
            effective_from_ms=start,effective_until_ms=end,observed_at_ms=end)
        schedule=replace(template.schedule,coverage_start_ms=start,coverage_end_ms=end,
            windows=(SessionWindow(start,end,'SYNTHETIC DECLARED CONTINUOUS WINDOW'),),observed_at_ms=end)
        self.instrument.write_text(json.dumps(spec.to_record())); self.schedule.write_text(json.dumps(schedule.to_record()))
        self.request['experiment_note']='Real BTC integration smoke only; unverified synthetic terms/calendar; previously seen.'
        self.request['jobs']=[self.job('base'),self.job('stress')]
        for job in self.request['jobs']:
            job['original_csv']=str(fixture.csv); job['volume_unit']='BTC'; job['config']['cash_currency']='USDT'
        self.save(); complete=self.run_review()
        report=json.loads((self.destination/'BATCH.json').read_bytes())
        self.assertEqual([j['replay']['intake']['candles'] for j in report['jobs']],[12,12])
        self.assertFalse(complete['reserved_performance_evaluated_by_this_operation'])
        self.assertIn('EXISTING REAL FIXTURE; ALREADY SEEN; SMOKE ONLY',(self.destination/'REVIEW.html').read_text())


if __name__=='__main__': unittest.main()
