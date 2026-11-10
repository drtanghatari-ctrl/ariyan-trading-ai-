"""Synthetic session-aware intake; no real exchange-calendar or venue-rule claims."""
import copy
import csv
import hashlib
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, localcontext, ROUND_UP, Inexact, Rounded
from pathlib import Path
from unittest.mock import patch

from symlink_fixture import symlink_or_skip

from ariyan_trading.instruments import (
    InstrumentIdentity,InstrumentSpec,AssetClass as A,ProductType as P,
    PriceDomain as PD,SettlementType as S,
)
from ariyan_trading.instrument_data import PRICE_BASIS
from ariyan_trading.market_data import HEADER,load_candles
from ariyan_trading.sessions import SessionSchedule,SessionWindow as W,CoverageKind as C,IntervalStatus as I
from ariyan_trading.session_data import load_session_candles,SessionCandleSeries,verify_session_report

H=3600000


def schedule(kind=C.EXHAUSTIVE):
    return SessionSchedule('SYNTHETIC-V1','UTC',0,10*H,kind,
        (W(H,4*H,'SYNTHETIC A'),W(6*H,8*H,'SYNTHETIC B')),'SYNTHETIC ONLY',10*H)


def spec():
    return InstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-VENUE','SHARE-1'),display_symbol='OTHER DISPLAY',
        asset_class=A.EQUITY,product=P.SHARE,underlying_label='SYNTHETIC COMPANY',
        quote_currency='USD',settlement_currency='USD',quantity_unit='SHARE',price_unit='USD_PER_SHARE',
        contract_multiplier='1',price_step='0.05',quantity_step='1',minimum_quantity='1',
        price_domain=PD.POSITIVE,settlement_type=S.SECURITY_DELIVERY,
        calendar_reference='SYNTHETIC-V1',timezone_label='UTC',corporate_action_reference='SYNTHETIC-ACTIONS',
        roll_reference='NOT_APPLICABLE',effective_from_ms=0,effective_until_ms=10*H,
        last_trade_ms=None,expiry_ms=None,source_label='SYNTHETIC TERMS',observed_at_ms=10*H)


def csv_bytes(opens=(H,3*H,6*H,7*H)):
    return (','.join(HEADER)+'\n'+''.join(f'{t},10.00,10.10,9.95,10.05,0.003\n' for t in opens)).encode()


class SessionDataA015Tests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.path=self.root/'candles.csv'

    def load(self,raw=None,**changes):
        self.path.write_bytes(csv_bytes() if raw is None else raw)
        args={'symbol':'SYNTH','source':'SYNTHETIC CSV','spec':spec(),'schedule':schedule(),
              'interval_ms':H,'anchor_ms':0,'first_open_ms':0,'end_exclusive_ms':10*H,'as_of_ms':10*H,
              'price_basis':PRICE_BASIS,'volume_unit':'SHARE','mapping_source':'CALLER SYNTHETIC MAPPING'}
        args.update(changes)
        return load_session_candles(self.path,**args)

    def test_gaps_preserved_and_missing_separate_from_closed(self):
        series=self.load();report=series.to_report();assessment=report['session_assessment']
        self.assertEqual(tuple(b.timestamp_ms for b in series.candles),(H,3*H,6*H,7*H))
        self.assertEqual(assessment['missing_session_opens'],[2*H])
        self.assertEqual(assessment['grid_slot_counts'][I.DECLARED_CLOSED.value],5)
        self.assertEqual(report['candles'],4)
        self.assertEqual(verify_session_report(series,report),report)

    def test_original_loader_and_replay_do_not_accept_the_new_series(self):
        from ariyan_trading.replay import run_replay
        series=self.load()
        with self.assertRaises(ValueError):load_candles(self.path,symbol='SYNTH',source='SYNTHETIC',interval_ms=H,as_of_ms=10*H)
        with self.assertRaises(ValueError):run_replay(series)

    def test_outside_session_observations_retained_not_dropped(self):
        series=self.load(csv_bytes((0,H,3*H,6*H,7*H)))
        self.assertEqual(len(series.candles),5)
        self.assertEqual(series.to_report()['session_assessment']['observations_outside_full_declared_sessions'],
                         [{'open_ms':0,'classification':I.DECLARED_CLOSED.value}])

    def test_partial_and_outside_schedule_coverage_stay_unknown(self):
        partial=self.load(csv_bytes((0,H)),schedule=schedule(C.PARTIAL)).to_report()['session_assessment']
        self.assertEqual(partial['grid_slot_counts'][I.DECLARED_CLOSED.value],0)
        self.assertEqual(partial['observations_outside_full_declared_sessions'][0]['classification'],I.UNKNOWN_UNLISTED.value)
        narrow=replace(schedule(),coverage_start_ms=H,coverage_end_ms=8*H)
        report=self.load(csv_bytes((0,H)),schedule=narrow).to_report()['session_assessment']
        self.assertEqual(report['observations_outside_full_declared_sessions'][0]['classification'],I.UNKNOWN_OUTSIDE_COVERAGE.value)

    def test_header_only_and_singleton_sources_preserve_absence(self):
        empty=self.load(csv_bytes(()));report=empty.to_report()
        self.assertEqual(empty.candles,())
        self.assertEqual(report['session_assessment']['missing_session_opens'],[H,2*H,3*H,6*H,7*H])
        self.assertEqual(len(self.load(csv_bytes((H,))).candles),1)

    def test_break_and_partial_bar_are_not_repaired(self):
        sc=replace(schedule(),windows=(W(H//2,3*H+H//2,'SYNTHETIC'),))
        series=self.load(csv_bytes((0,H,2*H,3*H)),schedule=sc)
        assessment=series.to_report()['session_assessment']
        self.assertEqual(assessment['expected_session_opens'],[H,2*H])
        self.assertEqual([r['open_ms'] for r in assessment['observations_outside_full_declared_sessions']],[0,3*H])
        self.assertEqual(len(series.candles),4)

    def test_explicit_non_epoch_anchor_accepts_session_phase(self):
        sc=replace(schedule(),windows=(W(H//2,7*H//2,'SYNTHETIC'),))
        series=self.load(csv_bytes((H//2,3*H//2,5*H//2)),schedule=sc,
                         anchor_ms=H//2,first_open_ms=H//2,end_exclusive_ms=9*H//2)
        self.assertEqual(series.to_report()['session_assessment']['missing_session_opens'],[])

    def test_reference_and_timezone_mismatches_rejected_before_io(self):
        for terms in (replace(spec(),calendar_reference='OTHER'),replace(spec(),timezone_label='America/New_York')):
            with self.assertRaisesRegex(ValueError,'calendar ID/timezone'):
                load_session_candles(self.root/'absent',symbol='SYNTH',source='SYNTHETIC',spec=terms,
                    schedule=schedule(),interval_ms=H,anchor_ms=0,first_open_ms=0,end_exclusive_ms=10*H,
                    as_of_ms=10*H,price_basis=PRICE_BASIS,volume_unit='SHARE',mapping_source='SYNTHETIC')

    def test_effective_and_last_trade_boundaries_cover_query_even_when_empty(self):
        for terms in (replace(spec(),effective_from_ms=1),replace(spec(),effective_until_ms=10*H-1)):
            with self.assertRaises(ValueError):self.load(csv_bytes(()),spec=terms)
        terms=replace(spec(),asset_class=A.ENERGY,product=P.FUTURE,quantity_unit='CONTRACT',
            corporate_action_reference='NOT_APPLICABLE',settlement_type=S.CASH,
            contract_multiplier='1000',roll_reference='SYNTHETIC-NO-AUTO-ROLL',last_trade_ms=10*H,expiry_ms=11*H)
        report=self.load(spec=terms,volume_unit='CONTRACT').to_report()
        self.assertEqual(report['instrument']['contract_multiplier'],'1000')
        with self.assertRaises(ValueError):self.load(spec=replace(terms,last_trade_ms=10*H-1),volume_unit='CONTRACT')

    def test_raw_and_value_hashes_are_distinct_and_include_all_rows(self):
        raw=csv_bytes();series=self.load(raw);a=series.to_report()
        self.assertEqual(series.raw_sha256,hashlib.sha256(raw).hexdigest())
        b=self.load(raw.replace(b'10.00',b'10.000')).to_report()
        self.assertNotEqual(a['source']['recorded_raw_sha256'],b['source']['recorded_raw_sha256'])
        self.assertEqual(a['canonical_candle_content_sha256'],b['canonical_candle_content_sha256'])
        c=self.load(csv_bytes((0,H,3*H,6*H,7*H))).to_report()
        self.assertNotEqual(a['canonical_candle_content_sha256'],c['canonical_candle_content_sha256'])

    def test_derived_subset_keeps_parent_hash_but_changes_content_hash(self):
        series=self.load();part=replace(series,candles=series.candles[:2])
        self.assertEqual(series.raw_sha256,part.raw_sha256)
        self.assertNotEqual(series.to_report()['canonical_candle_content_sha256'],part.to_report()['canonical_candle_content_sha256'])
        with self.assertRaises(ValueError):verify_session_report(part,series.to_report())

    def test_report_tampering_metadata_terms_and_type_confusion_rejected(self):
        series=self.load();base=series.to_report()
        cases=[{**base,'extra':1},{**base,'candles':True},{**base,'live_authorized':True},
               {**base,'intake_sha256':'0'*64},{k:v for k,v in base.items() if k!='instrument'}]
        nested=copy.deepcopy(base);nested['session_assessment']['missing_session_opens']=[];cases.append(nested)
        for report in cases:
            with self.assertRaises(ValueError):verify_session_report(series,report)
        for altered in (replace(series,mapping_source='OTHER'),replace(series,spec=replace(spec(),price_step='0.01')),
                        replace(series,schedule=replace(schedule(),coverage_kind=C.PARTIAL))):
            with self.assertRaises(ValueError):verify_session_report(altered,base)

    def test_bad_headers_rows_empty_file_and_broken_csv_reject_whole_input(self):
        for raw in (b'',b'wrong,header\n',csv_bytes()+b'\n',csv_bytes()+b'1,2,3\n',
                    b','.join(s.encode() for s in HEADER)+b'\n"unfinished'):
            with self.assertRaises((ValueError,csv.Error)):self.load(raw)

    def test_negative_zero_nonfinite_bad_ohlc_and_price_grid_rejected(self):
        for raw in (csv_bytes().replace(b'10.00',b'-1'),csv_bytes().replace(b'10.00',b'0'),
                    csv_bytes().replace(b'10.00',b'NaN'),csv_bytes().replace(b'9.95',b'11.00'),
                    csv_bytes().replace(b'10.05',b'10.06'),csv_bytes().replace(b'0.003',b'-1')):
            with self.assertRaises(ValueError):self.load(raw)
        # An A012 signed-domain declaration does not enable signed candles here.
        with self.assertRaises(ValueError):self.load(csv_bytes().replace(b'10.00',b'-1'),spec=replace(spec(),price_domain=PD.SIGNED))

    def test_aggregate_volume_is_not_an_order_quantity(self):
        series=self.load(csv_bytes().replace(b'0.003',b'0'))
        self.assertTrue(all(b.volume==0 for b in series.candles))
        self.assertEqual(len(self.load().candles),4)  # 0.003 is off the SHARE order grid of 1.

    def test_duplicate_unordered_offgrid_outofrange_and_future_times_rejected(self):
        for opens in ((H,H),(3*H,H),(H+1,),(10*H,),(-H,)):
            with self.assertRaises(ValueError):self.load(csv_bytes(opens))
        with self.assertRaises(ValueError):self.load(as_of_ms=9*H)

    def test_resource_limits_and_invalid_declarations(self):
        import ariyan_trading.session_data as module
        with patch.object(module,'MAX_BYTES',5):
            with self.assertRaises(ValueError):self.load()
        with patch.object(module,'MAX_ROWS',2):
            with self.assertRaises(ValueError):self.load()
        for changes in ({'price_basis':'ADJUSTED'},{'volume_unit':'USD'},{'symbol':True},
                        {'mapping_source':' '},{'interval_ms':True},{'source':'bad\nsource'}):
            with self.assertRaises(ValueError):self.load(**changes)

    def test_symlink_source_is_not_followed_and_source_never_modified(self):
        series=self.load();before=self.path.read_bytes();link=self.root/'linked.csv'
        symlink_or_skip(link, self.path)
        with self.assertRaises(ValueError):load_session_candles(link,symbol=series.symbol,source=series.source,
            spec=series.spec,schedule=series.schedule,interval_ms=H,anchor_ms=0,first_open_ms=0,
            end_exclusive_ms=10*H,as_of_ms=10*H,price_basis=PRICE_BASIS,volume_unit='SHARE',mapping_source='SYNTHETIC')
        self.assertEqual(self.path.read_bytes(),before)

    def test_immutability_record_mutation_isolation_and_no_authority_flags(self):
        series=self.load();before=series.to_report();report=series.to_report()
        with self.assertRaises(FrozenInstanceError):series.symbol='CHANGED'
        report['instrument']['identity']['venue']='CHANGED'
        self.assertEqual(series.to_report(),before)
        for key in ('source_independently_authenticated','instrument_mapping_independently_verified',
                    'calendar_independently_verified','point_in_time_availability_established',
                    'session_aware_replay_available','live_authorized'):
            self.assertIs(before[key],False)

    def test_decimal_context_isolation(self):
        expected=self.load().to_report()
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
            self.assertEqual(self.load().to_report(),expected)

    def test_real_fixture_canonical_conversion_smoke_only(self):
        root=Path(__file__).resolve().parents[1]
        start=1704067200000;end=1704153600000
        original=load_candles(root/'examples/a007/BTCUSDT-1h-2024-01-01.csv',
            symbol='BTCUSDT',source='Existing fixture smoke only',interval_ms=H,as_of_ms=end,
            input_format='binance-spot',timestamp_unit='ms')
        raw=(','.join(HEADER)+'\n'+''.join(','.join(str(v) for v in
            (b.timestamp_ms,b.open,b.high,b.low,b.close,b.volume))+'\n' for b in original.candles)).encode()
        sc=SessionSchedule('SYNTHETIC-V1','UTC',start,end,C.EXHAUSTIVE,
            (W(start,end,'SYNTHETIC FULL-DAY DECLARATION'),),'SYNTHETIC SCHEDULE; NOT AUTHENTICATED',end)
        terms=replace(spec(),asset_class=A.CRYPTO,product=P.SPOT,quantity_unit='TEST_BASE_UNIT',
            corporate_action_reference='NOT_APPLICABLE',settlement_type=S.ASSET_DELIVERY,
            effective_from_ms=start,effective_until_ms=end,price_step='0.00000001',observed_at_ms=end)
        series=self.load(raw,symbol='BTCUSDT',spec=terms,schedule=sc,volume_unit='TEST_BASE_UNIT',
            first_open_ms=start,end_exclusive_ms=end,as_of_ms=end)
        self.assertEqual(series.candles,original.candles)
        self.assertEqual(series.to_report()['session_assessment']['missing_session_opens'],[])
        self.assertEqual(series.raw_sha256,hashlib.sha256(raw).hexdigest())
        self.assertNotEqual(series.raw_sha256,original.raw_sha256)  # Derived CSV, not original Binance bytes.


if __name__=='__main__':unittest.main()
