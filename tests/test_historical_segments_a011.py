"""Native timestamps, quarantined rows and contiguous history coverage."""
import csv
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from ariyan_trading import historical_segments as h
from ariyan_trading.market_data import CandleDataset,load_candles
ROOT=Path(__file__).resolve().parents[1]

class HistoryIndexTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.folder=Path(tmp.name);self.path=self.folder/'input.csv'
        self.options=dict(symbol='BTCUSDT',source='SYNTHETIC A011 TEST ONLY',interval_ms=60000,as_of_ms=1000000)
    def write(self,opens=(0,60000,120000,180000),changes=None,unit='ms'):
        scale=1000 if unit=='us' else 1;rows=[]
        for i,t in enumerate(opens):
            row=[str(t*scale),'100','110','90','105','1',str((t+60000)*scale-1),'0','1','0','0','0']
            for key,value in (changes or {}).get(i,{}).items():row[key]=str(value)
            rows.append(','.join(row))
        self.path.write_bytes(('\n'.join(rows)+'\n').encode('ascii'))
    def inspect(self,**kwargs):return h.inspect_history(self.path,**{**self.options,**kwargs})
    def cli(self,output):
        return subprocess.run([sys.executable,'-m','ariyan_trading.historical_segments','--csv',str(self.path),
            '--symbol','BTCUSDT','--source',self.options['source'],'--interval-ms','60000',
            '--as-of-ms','1000000','--output',str(output)],cwd=ROOT,
            env={**os.environ,'PYTHONPATH':str(ROOT/'app')},capture_output=True,text=True)

    def test_valid_source_exact_hash_metadata_and_span(self):
        self.write();raw=self.path.read_bytes();index=self.inspect();report=index.to_report()
        self.assertEqual(index.raw_sha256,hashlib.sha256(raw).hexdigest())
        self.assertEqual((report['source_rows'],report['complete_rows'],report['excluded_rows'],report['missing_rows']),(4,4,0,0))
        self.assertTrue(report['whole_source_accepted_for_contiguous_replay'])
        self.assertFalse(report['live_authorized'])
        self.assertEqual((index.first_source_open_ms,index.last_source_open_ms),(0,180000))
        self.assertTrue(index.complete_window(0,240000))
        self.assertEqual(self.path.read_bytes(),raw)

    def test_partial_row_is_quarantined_and_splits_native_time(self):
        self.write((0,60000,120000,180000,240000),{2:{6:150000}});index=self.inspect()
        self.assertEqual([b.timestamp_ms for b in index.candles],[0,60000,180000,240000])
        self.assertEqual(index.exclusions[0].reasons,('PARTIAL_INTERVAL',))
        self.assertEqual((index.exclusions[0].line,index.exclusions[0].published_close_raw),(3,'150000'))
        self.assertEqual([s.end_index_exclusive-s.start_index for s in index.spans],[2,2])
        self.assertFalse(index.complete_window(60000,240000))
        self.assertTrue(index.complete_window(180000,300000))
        self.assertFalse(index.to_report()['whole_source_accepted_for_contiguous_replay'])

    def test_missing_interval_is_not_imputed(self):
        self.write((0,60000,180000,240000));index=self.inspect()
        self.assertEqual([b.timestamp_ms for b in index.candles],[0,60000,180000,240000])
        gap=index.missing[0]
        self.assertEqual((gap.first_missing_open_ms,gap.end_exclusive_ms,gap.missing_rows),(120000,180000,1))
        self.assertFalse(index.complete_window(0,300000))

    def test_partial_and_missing_are_separate_counts(self):
        self.write((0,60000,120000,240000,300000),{2:{6:150000}});r=self.inspect().to_report()
        self.assertEqual((r['source_rows'],r['complete_rows'],r['excluded_rows'],r['missing_rows']),(5,4,1,1))

    def test_invalid_close_metadata_is_explicitly_excluded(self):
        for value in ('59999','120000','NaN','-1'):
            self.write((0,60000,120000),{1:{6:value}})
            self.assertEqual(self.inspect().exclusions[0].reasons,('INVALID_CLOSE_TIME',))

    def test_invalid_ohlcv_never_becomes_complete(self):
        for key,value in ((1,'0'),(2,'99'),(3,'106'),(4,'NaN'),(5,'-1'),(4,'1e100')):
            self.write((0,60000,120000),{1:{key:value}});index=self.inspect()
            self.assertIn('INVALID_OHLCV',index.exclusions[0].reasons)
            self.assertEqual(len(index.candles),2)

    def test_complete_zero_volume_bar_is_retained(self):
        self.write(changes={1:{5:0}});index=self.inspect()
        self.assertEqual(len(index.candles),4)
        self.assertEqual(index.candles[1].volume,0)
        self.assertEqual(index.exclusions,())

    def test_bad_open_order_grid_and_location_reject_entire_file(self):
        for opens in ((0,0),(60000,0),(0,60001)):
            self.write(opens)
            with self.assertRaises(ValueError):self.inspect()
        for value in ('bad','-60000','60000.1'):
            self.write(changes={1:{0:value}})
            with self.assertRaises(ValueError):self.inspect()

    def test_wrong_shape_empty_blank_and_broken_csv_reject(self):
        for raw in ('','\n','0,1,2\n','"unclosed',','.join(['0']*13)+'\n'):
            self.path.write_text(raw)
            with self.assertRaises((ValueError,csv.Error)):self.inspect()

    def test_metadata_future_and_resource_bounds_reject(self):
        self.write()
        for kwargs in (dict(symbol='bad symbol'),dict(source=''),dict(interval_ms=True),dict(interval_ms=0),
                       dict(as_of_ms=True),dict(as_of_ms=239999),dict(timestamp_unit='guess')):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):self.inspect(**kwargs)
        with patch.object(h,'MAX_BYTES',10),self.assertRaises(ValueError):self.inspect()
        with patch.object(h,'MAX_ROWS',2),self.assertRaises(ValueError):self.inspect()

    def test_explicit_units_and_fractional_open(self):
        self.write();a=self.inspect()
        self.write(unit='us');b=self.inspect(timestamp_unit='us')
        self.assertEqual(a.candles,b.candles);self.assertEqual(a.spans,b.spans)
        self.write(changes={1:{0:'60000001'}},unit='us')
        with self.assertRaises(ValueError):self.inspect(timestamp_unit='us')

    def test_singletons_and_fully_excluded_sources(self):
        self.write((0,120000));index=self.inspect()
        self.assertEqual(len(index.spans),2);self.assertTrue(index.complete_window(0,60000))
        with self.assertRaises(ValueError):index.contiguous_dataset(0)
        self.write((0,));self.assertFalse(self.inspect().to_report()['whole_source_accepted_for_contiguous_replay'])
        self.write((0,),{0:{6:0}});index=self.inspect()
        self.assertEqual((len(index.candles),len(index.exclusions)),(0,1))
        self.assertFalse(index.complete_window(0,60000))

    def test_export_verified_span_and_original_strict_intake_remains_strict(self):
        self.write((0,60000,120000,240000,300000),{2:{6:150000}});index=self.inspect()
        a=index.contiguous_dataset(0);b=index.contiguous_dataset(1)
        self.assertIs(type(a),CandleDataset);self.assertEqual(a.raw_sha256,index.raw_sha256)
        self.assertEqual([x.timestamp_ms for x in a.candles],[0,60000])
        self.assertEqual([x.timestamp_ms for x in b.candles],[240000,300000])
        for n in (True,-1,2):
            with self.assertRaises(ValueError):index.contiguous_dataset(n)
        with self.assertRaises(ValueError):load_candles(self.path,**self.options,input_format='binance-spot')

    def test_window_bounds_and_outside_coverage(self):
        self.write();index=self.inspect()
        for start,end in ((True,60000),(0,0),(60000,0),(1,60000),(0,60001)):
            with self.assertRaises(ValueError):index.complete_window(start,end)
        self.assertFalse(index.complete_window(0,300000));self.assertFalse(index.complete_window(240000,300000))

    def test_contiguous_file_boundary_is_not_a_gap(self):
        self.write((0,60000));a=self.inspect()
        self.write((120000,180000));b=self.inspect()
        self.assertTrue(h.complete_history_window((a,b),0,240000))
        self.write((180000,240000));c=self.inspect()
        self.assertFalse(h.complete_history_window((a,c),0,300000))
        self.assertTrue(h.complete_history_window((a,c),180000,300000))

    def test_every_source_order_and_identity_checked_before_early_success(self):
        self.write((0,60000));a=self.inspect()
        self.write((60000,120000));overlap=self.inspect()
        self.write((120000,180000));b=self.inspect()
        for indexes in ((a,overlap),(b,a),(a,replace(b,symbol='ETHUSDT')),
                        (a,replace(b,interval_ms=120000)),(a,object()),(),None):
            with self.assertRaises(ValueError):h.complete_history_window(indexes,0,60000)

    def test_original_byte_hash_not_normalized_values(self):
        self.write();a=self.inspect();self.path.write_bytes(self.path.read_bytes().replace(b'\n',b'\r\n'))
        b=self.inspect();self.assertEqual(a.candles,b.candles);self.assertNotEqual(a.raw_sha256,b.raw_sha256)

    def test_cli_determinism_no_input_or_output_overwrite(self):
        self.write((0,60000,120000,240000,300000),{2:{6:150000}});raw=self.path.read_bytes()
        a=self.folder/'a.json';b=self.folder/'b.json'
        for path in (a,b):
            result=self.cli(path);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(a.read_bytes(),b.read_bytes());before=a.read_bytes()
        self.assertEqual(self.cli(a).returncode,2);self.assertEqual(a.read_bytes(),before)
        self.assertEqual(self.cli(self.path).returncode,2);self.assertEqual(self.path.read_bytes(),raw)

    def test_cli_failure_creates_no_report(self):
        self.path.write_text('invalid\n');output=self.folder/'absent.json'
        self.assertEqual(self.cli(output).returncode,2);self.assertFalse(output.exists())

    def test_real_excerpt_exact_provenance_and_quality_counts(self):
        folder=ROOT/'examples/a011';metadata=json.loads((folder/'SOURCE.json').read_text())
        path=folder/'BTCUSDT-1h-2021-02-excerpt.csv'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),metadata['excerpt_sha256'])
        options=dict(symbol='BTCUSDT',source='Derived real excerpt; intake smoke only',interval_ms=3600000,as_of_ms=1614556800000)
        index=h.inspect_history(path,**options)
        self.assertEqual((len(index.candles),len(index.exclusions),sum(g.missing_rows for g in index.missing)),(4,1,1))
        self.assertEqual([s.end_index_exclusive-s.start_index for s in index.spans],[2,2])
        with self.assertRaises(ValueError):load_candles(path,**options,input_format='binance-spot')

if __name__=='__main__':unittest.main()
