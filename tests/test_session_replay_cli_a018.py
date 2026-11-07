"""A018 command/file mechanics; real fixture smoke uses synthetic unverified terms."""
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from test_session_replay_a017 import series as synthetic_series, config as synthetic_config
from ariyan_trading import session_replay_cli as cli
from ariyan_trading.market_data import HEADER,load_candles
from ariyan_trading.session_replay import run_session_replay
from ariyan_trading.sessions import SessionSchedule,SessionWindow as W,CoverageKind as C
from ariyan_trading.instruments import AssetClass as A,ProductType as P,SettlementType as S

ROOT=Path(__file__).resolve().parents[1]
H=3600000


class SessionReplayCliA018Tests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.root=Path(temp.name).resolve();self.output=self.root/'report.json'
        self.csv=self.root/'candles.csv';self.instrument=self.root/'instrument.json';self.schedule=self.root/'schedule.json'
        self.inputs()

    def inputs(self,s=None):
        self.s=s or synthetic_series()
        self.instrument.write_text(json.dumps(self.s.spec.to_record()))
        self.schedule.write_text(json.dumps(self.s.schedule.to_record()))
        self.csv.write_text(','.join(HEADER)+'\n'+''.join(','.join(str(v) for v in
            (b.timestamp_ms,b.open,b.high,b.low,b.close,b.volume))+'\n' for b in self.s.candles))

    def args(self,**overrides):
        s=self.s
        fields={'csv':self.csv,'instrument':self.instrument,'schedule':self.schedule,'output':self.output,
            'symbol':s.symbol,'source':s.source,'mapping-source':s.mapping_source,'volume-unit':s.volume_unit,
            'interval-ms':s.interval_ms,'anchor-ms':s.anchor_ms,'first-open-ms':s.first_open_ms,
            'end-exclusive-ms':s.end_exclusive_ms,'as-of-ms':s.as_of_ms,'price-basis':s.price_basis,
            'opening-cash':'1000','cash-currency':s.spec.quote_currency,'cash-step':'0.01','fee-bps':'10',
            'slippage-bps':'10','price-convention':synthetic_config().price_convention,
            'short-window':1,'long-window':2,'max-close-drawdown-pct':'100'}
        fields.update(overrides)
        return [part for name,value in fields.items() for part in ('--'+name,str(value))]

    def process(self,**changes):
        return subprocess.run([sys.executable,'-m','ariyan_trading.session_replay_cli',*self.args(**changes)],
            cwd=ROOT,env={**os.environ,'PYTHONPATH':str(ROOT/'app')},capture_output=True,text=True)

    def rejected(self,**changes):
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as failure:
            cli.main(self.args(**changes))
        self.assertEqual(failure.exception.code,2)
        self.assertFalse(self.output.exists())

    def test_real_command_matches_direct_engine_and_preserves_inputs(self):
        originals={p:p.read_bytes() for p in (self.csv,self.instrument,self.schedule)}
        result=self.process();self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(self.output.read_bytes())
        s=replace(self.s,raw_sha256=hashlib.sha256(originals[self.csv]).hexdigest())
        self.assertEqual(report['replay'],run_session_replay(s,synthetic_config()))
        self.assertEqual(report['input_bytes_sha256'],{
            'csv':hashlib.sha256(originals[self.csv]).hexdigest(),
            'instrument_json':hashlib.sha256(originals[self.instrument]).hexdigest(),
            'schedule_json':hashlib.sha256(originals[self.schedule]).hexdigest()})
        self.assertEqual({p:p.read_bytes() for p in originals},originals)
        self.assertIn('NO LIVE ACTIONS',result.stdout)
        self.assertIn('session_replay.py',report['source_file_sha256'])
        self.assertIn('session_replay_cli.py',report['source_file_sha256'])
        self.assertFalse(report['live_authorized']);self.assertFalse(report['strategy_promoted'])

    def test_fresh_process_deterministic_reports_and_run_hash(self):
        self.assertEqual(self.process().returncode,0)
        other=self.root/'other.json'
        run=self.process(output=other);self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(self.output.read_bytes(),other.read_bytes())
        report=json.loads(self.output.read_bytes());digest=report.pop('run_sha256')
        raw=json.dumps(report,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')
        self.assertEqual(digest,hashlib.sha256(b'ARIYAN-A018-SESSION-REPLAY-RUN-V1\0'+raw).hexdigest())

    def test_existing_report_is_never_overwritten(self):
        self.output.write_bytes(b'keep')
        result=self.process();self.assertEqual(result.returncode,2)
        self.assertEqual(self.output.read_bytes(),b'keep')

    def test_output_cannot_replace_any_input(self):
        for path in (self.csv,self.instrument,self.schedule):
            before=path.read_bytes();result=self.process(output=path)
            self.assertEqual(result.returncode,2);self.assertEqual(path.read_bytes(),before)
        self.assertFalse(self.output.exists())

    def test_missing_output_parent_is_not_created(self):
        parent=self.root/'missing'
        result=self.process(output=parent/'report.json')
        self.assertEqual(result.returncode,2);self.assertFalse(parent.exists())

    def test_duplicate_json_keys_rejected(self):
        self.instrument.write_text('{"version":"one","version":"two"}')
        self.rejected()

    def test_nonfinite_nonobject_and_invalid_json_rejected(self):
        for text in ('{"x":NaN}','[]','{"x":Infinity}','{broken'):
            self.inputs();self.schedule.write_text(text);self.rejected()

    def test_unknown_instrument_fields_and_upgraded_claims_rejected(self):
        for key,value in (('extra',1),('source_independently_authenticated',True),('price_step',0.05)):
            self.inputs();record=json.loads(self.instrument.read_bytes());record[key]=value
            self.instrument.write_text(json.dumps(record));self.rejected()

    def test_wrong_calendar_reference_and_partial_coverage_rejected(self):
        record=json.loads(self.instrument.read_bytes());record['calendar_reference']='OTHER'
        self.instrument.write_text(json.dumps(record));self.rejected()
        self.inputs(synthetic_series());self.inputs(replace(self.s,schedule=replace(self.s.schedule,coverage_kind=C.PARTIAL)))
        self.rejected()

    def test_missing_or_bad_candle_data_publishes_nothing(self):
        raw=self.csv.read_text().splitlines()
        self.csv.write_text('\n'.join(raw[:4]+raw[5:])+'\n');self.rejected()
        self.inputs();self.csv.write_text(self.csv.read_text().replace(',10,',',NaN,',1));self.rejected()

    def test_cost_currency_and_interval_configuration_errors(self):
        for changes in ({'fee-bps':'NaN'},{'cash-currency':'EUR'},{'interval-ms':'not-an-int'},
                        {'as-of-ms':self.s.end_exclusive_ms-1},{'cash-step':'0'}, {'max-trades':'0'}):
            self.rejected(**changes)

    def test_required_price_convention_and_basis_not_silently_defaulted(self):
        args=self.args();index=args.index('--price-convention');del args[index:index+2]
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as failure:cli.main(args)
        self.assertEqual(failure.exception.code,2);self.assertFalse(self.output.exists())
        self.rejected(**{'price-basis':'ADJUSTED'})

    def test_metadata_and_report_byte_limits_before_output_creation(self):
        for field in ('MAX_SPEC_BYTES','MAX_SCHEDULE_BYTES','MAX_REPORT_BYTES'):
            with patch.object(cli,field,1):self.rejected()

    def test_symlink_inputs_and_output_rejected_without_following(self):
        linked=self.root/'linked.json';linked.symlink_to(self.instrument)
        self.rejected(instrument=linked)
        destination=self.root/'linked-output.json';destination.symlink_to(self.instrument)
        before=self.instrument.read_bytes();self.rejected(output=destination)
        self.assertEqual(self.instrument.read_bytes(),before)

    def test_input_change_during_replay_is_detected(self):
        original=cli.run_session_replay
        def changing(series,config):
            result=original(series,config)
            with self.instrument.open('ab') as stream:stream.write(b' ')
            return result
        with patch.object(cli,'run_session_replay',side_effect=changing):self.rejected()

    def test_source_change_recheck_prevents_publication(self):
        before=cli._sources();after={**before,'session_replay.py':'0'*64}
        with patch.object(cli,'_sources',side_effect=[before,after]):self.rejected()

    def test_failed_write_cleans_only_its_own_partial_report(self):
        original=Path.open;target=self.output
        class Broken:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,raw):
                self.stream.write(raw[:10]);raise OSError('Synthetic output interruption')
        def fail(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return Broken(stream) if path==target and args and args[0]=='xb' else stream
        with patch.object(Path,'open',new=fail):self.rejected()

    def test_output_creation_race_preserves_other_writers_file(self):
        original=cli._write
        def racing(path,raw):
            path.write_bytes(b'concurrent writer')
            return original(path,raw)
        with patch('sys.stderr',new=io.StringIO()),patch.object(cli,'_write',side_effect=racing),self.assertRaises(SystemExit):
            cli.main(self.args())
        self.assertEqual(self.output.read_bytes(),b'concurrent writer')

    def test_csv_unchanged_even_when_engine_preflight_rejects_it(self):
        self.inputs(replace(self.s,schedule=replace(self.s.schedule,windows=(W(H,12*H,'SYNTHETIC'),))))
        before=self.csv.read_bytes();self.rejected();self.assertEqual(self.csv.read_bytes(),before)

    def test_real_fixture_cli_integration_smoke_only(self):
        start=1704067200000;end=1704153600000
        original=load_candles(ROOT/'examples/a007/BTCUSDT-1h-2024-01-01.csv',symbol='BTCUSDT',
            source='Existing fixture smoke only',interval_ms=H,as_of_ms=end,input_format='binance-spot')
        sc=SessionSchedule('SYNTHETIC-V1','UTC',start,end,C.EXHAUSTIVE,(W(start,end,'SYNTHETIC FULL DAY'),),
            'SYNTHETIC CALENDAR; NOT VERIFIED VENUE DATA',end)
        terms=replace(self.s.spec,asset_class=A.CRYPTO,product=P.SPOT,quantity_unit='BTC',price_unit='USDT_PER_BTC',
            quote_currency='USDT',settlement_currency='USDT',price_step='0.00000001',quantity_step='0.00000001',
            minimum_quantity='0.00000001',corporate_action_reference='NOT_APPLICABLE',settlement_type=S.ASSET_DELIVERY,
            effective_from_ms=start,effective_until_ms=end,observed_at_ms=end)
        s=replace(self.s,candles=original.candles,symbol='BTCUSDT',spec=terms,schedule=sc,volume_unit='BTC',
                  first_open_ms=start,end_exclusive_ms=end,as_of_ms=end)
        self.inputs(s);run=self.process();self.assertEqual(run.returncode,0,run.stderr)
        report=json.loads(self.output.read_bytes());self.assertEqual(report['replay']['intake']['candles'],24)
        self.assertEqual(report['input_bytes_sha256']['csv'],hashlib.sha256(self.csv.read_bytes()).hexdigest())
        self.assertNotEqual(report['input_bytes_sha256']['csv'],original.raw_sha256)
        self.assertFalse(report['source_independently_authenticated']);self.assertFalse(report['strategy_promoted'])


if __name__=='__main__':unittest.main()
