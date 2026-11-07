"""Synthetic UTC schedules only; no authoritative exchange calendar fixtures."""
import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.sessions import (
    CoverageKind as C, IntervalStatus as I, SessionWindow as W, SessionSchedule,
    assess_observation_times, schedule_from_record, MAX_TIMESTAMP_MS,
)

H=3600000
D=24*H


def schedule(kind=C.EXHAUSTIVE):
    return SessionSchedule('SYNTHETIC-SESSIONS-V1','UTC',0,10*H,kind,
        (W(H,4*H,'SYNTHETIC A'),W(6*H,8*H,'SYNTHETIC B')),
        'SYNTHETIC DECLARATION ONLY',12*H)


def assess(s=None,observed=(H,3*H,6*H,7*H),**changes):
    kwargs={'interval_ms':H,'anchor_ms':0,'first_open_ms':0,'end_exclusive_ms':10*H,'as_of_ms':10*H}
    kwargs.update(changes)
    return assess_observation_times(s or schedule(),observed,**kwargs)


class SessionsA014Tests(unittest.TestCase):
    def test_missing_session_slots_are_separate_from_declared_closures(self):
        report=assess()
        self.assertEqual(report['expected_session_opens'],[H,2*H,3*H,6*H,7*H])
        self.assertEqual(report['missing_session_opens'],[2*H])
        self.assertEqual(report['observed_session_bars'],4)
        self.assertEqual(report['grid_slot_counts'][I.DECLARED_CLOSED.value],5)
        self.assertEqual(sum(report['grid_slot_counts'].values()),10)

    def test_partial_schedule_never_certifies_unlisted_gaps_as_closed(self):
        report=assess(schedule(C.PARTIAL))
        self.assertEqual(report['grid_slot_counts'][I.DECLARED_CLOSED.value],0)
        self.assertEqual(report['grid_slot_counts'][I.UNKNOWN_UNLISTED.value],5)
        self.assertEqual(report['missing_session_opens'],[2*H])

    def test_outside_coverage_is_unknown_even_with_exhaustive_declaration(self):
        s=replace(schedule(),coverage_start_ms=2*H,coverage_end_ms=8*H,
                  windows=(W(3*H,5*H,'SYNTHETIC'),))
        report=assess(s,observed=(4*H,))
        self.assertEqual(report['grid_slot_counts'][I.UNKNOWN_OUTSIDE_COVERAGE.value],4)
        self.assertEqual(report['missing_session_opens'],[3*H])

    def test_half_open_boundaries_and_crossing_intervals(self):
        s=SessionSchedule('SYNTH','UTC',0,300,C.EXHAUSTIVE,(W(100,200,'SYNTH'),),'SYNTH',300)
        for opened,closed,status in ((100,200,I.WITHIN_SESSION),(90,100,I.DECLARED_CLOSED),
            (200,210,I.DECLARED_CLOSED),(90,110,I.CROSSES_BOUNDARY),(190,210,I.CROSSES_BOUNDARY),
            (0,300,I.CROSSES_BOUNDARY),(299,301,I.UNKNOWN_OUTSIDE_COVERAGE)):
            self.assertIs(s.classify_interval(opened,closed),status)

    def test_adjacent_sessions_are_not_implicitly_merged(self):
        s=SessionSchedule('SYNTH','UTC',0,300,C.EXHAUSTIVE,
            (W(0,100,'A'),W(100,200,'B')),'SYNTH',300)
        self.assertIs(s.classify_interval(0,200),I.CROSSES_BOUNDARY)
        self.assertIs(s.classify_interval(100,200),I.WITHIN_SESSION)

    def test_partial_closing_bar_is_not_shortened_or_counted_as_missing(self):
        s=replace(schedule(),windows=(W(0,6*H+H//2,'SYNTHETIC EARLY CLOSE'),))
        report=assess(s,observed=())
        self.assertEqual(report['missing_session_opens'],[i*H for i in range(6)])
        self.assertEqual(report['grid_slot_counts'][I.CROSSES_BOUNDARY.value],1)
        self.assertNotIn(6*H,report['missing_session_opens'])

    def test_explicit_anchor_supports_non_epoch_session_bar_phase(self):
        s=replace(schedule(),windows=(W(H//2,3*H+H//2,'SYNTHETIC'),))
        report=assess(s,observed=(H//2,3*H//2,5*H//2),anchor_ms=H//2,
                      first_open_ms=H//2,end_exclusive_ms=4*H+H//2)
        self.assertEqual(report['missing_session_opens'],[])
        self.assertEqual(report['observed_session_bars'],3)

    def test_breaks_and_overnight_windows_preserve_native_utc_time(self):
        s=SessionSchedule('SYNTH-NIGHT','UTC',0,2*D,C.EXHAUSTIVE,
            (W(22*H,24*H,'NIGHT A'),W(25*H,27*H,'NIGHT B')),'SYNTHETIC ONLY',2*D)
        report=assess(s,observed=(),first_open_ms=22*H,end_exclusive_ms=28*H,as_of_ms=2*D)
        self.assertEqual(report['missing_session_opens'],[22*H,23*H,25*H,26*H])
        self.assertEqual(report['grid_slot_counts'][I.DECLARED_CLOSED.value],2)

    def test_explicit_utc_offset_change_is_used_without_local_time_inference(self):
        # Synthetic UTC windows illustrate a changed opening offset; not actual DST dates.
        s=SessionSchedule('SYNTH-OFFSET','America/New_York',0,4*D,C.EXHAUSTIVE,
            (W(14*H+H//2,16*H+H//2,'A'),W(3*D+13*H+H//2,3*D+15*H+H//2,'B')),
            'SYNTHETIC OFFSETS; NO TZ DATABASE VERIFICATION',4*D)
        self.assertIs(s.classify_interval(13*H+H//2,14*H+H//2),I.DECLARED_CLOSED)
        self.assertIs(s.classify_interval(3*D+13*H+H//2,3*D+14*H+H//2),I.WITHIN_SESSION)
        self.assertFalse(s.to_record()['timezone_conversion_verified'])

    def test_observations_in_closed_unknown_and_boundary_slots_are_retained(self):
        report=assess(observed=(0,H,3*H,6*H,7*H))
        self.assertEqual(report['observations_outside_full_declared_sessions'],
                         [{'open_ms':0,'classification':I.DECLARED_CLOSED.value}])
        self.assertEqual(report['missing_session_opens'],[2*H])
        partial=assess(schedule(C.PARTIAL),observed=(0,))
        self.assertEqual(partial['observations_outside_full_declared_sessions'][0]['classification'],I.UNKNOWN_UNLISTED.value)
        crossing=assess(replace(schedule(),windows=(W(H//2,3*H,'SYNTH'),)),observed=(0,))
        self.assertEqual(crossing['observations_outside_full_declared_sessions'][0]['classification'],I.CROSSES_BOUNDARY.value)

    def test_empty_exhaustive_and_partial_schedules_have_distinct_meanings(self):
        for kind,status in ((C.EXHAUSTIVE,I.DECLARED_CLOSED),(C.PARTIAL,I.UNKNOWN_UNLISTED)):
            report=assess(replace(schedule(kind),windows=()),observed=())
            self.assertEqual(report['expected_session_opens'],[])
            self.assertEqual(report['grid_slot_counts'][status.value],10)

    def test_invalid_window_times_order_overlap_and_coverage(self):
        for opened,closed in ((1,1),(2,1),(-1,1),(True,10),(0,MAX_TIMESTAMP_MS+1)):
            with self.assertRaises(ValueError):W(opened,closed,'SYNTH')
        for windows in ((W(2*H,5*H,'A'),W(4*H,6*H,'B')),
                        tuple(reversed(schedule().windows)),(W(0,11*H,'A'),),[W(0,H,'A')],(object(),)):
            with self.assertRaises(ValueError):replace(schedule(),windows=windows)

    def test_labels_types_and_coverage_bounds_rejected(self):
        for key,value in (('schedule_id','bad id'),('timezone_label','EST'),('source_label',' '),
                          ('coverage_kind','CALLER_DECLARES_EXHAUSTIVE_WINDOWS'),('coverage_start_ms',True),
                          ('coverage_end_ms',0),('observed_at_ms',-1)):
            with self.assertRaises(ValueError):replace(schedule(),**{key:value})
        with self.assertRaises(ValueError):W(0,1,'bad\nlabel')

    def test_observed_timestamp_shape_order_duplicates_range_and_grid_rejected(self):
        for values in ([H],(H,H),(2*H,H),(1,),(True,),(10*H,),(-H,)):
            with self.assertRaises(ValueError):assess(observed=values)

    def test_grid_asof_and_range_type_confusion_rejected(self):
        for changes in ({'interval_ms':True},{'interval_ms':0},{'anchor_ms':-1},
                        {'first_open_ms':1},{'end_exclusive_ms':10*H-1},
                        {'as_of_ms':9*H},{'first_open_ms':10*H},{'as_of_ms':True}):
            with self.assertRaises(ValueError):assess(**changes)

    def test_resource_limits_checked_before_grid_or_window_expansion(self):
        with self.assertRaises(ValueError):
            assess(interval_ms=1,end_exclusive_ms=100001,as_of_ms=100001,observed=())
        with self.assertRaises(ValueError):replace(schedule(),windows=(W(0,1,'SYNTH'),)*10001)
        with self.assertRaises(ValueError):assess(observed=(0,)*100001)

    def test_schedule_serialization_and_fingerprints_bind_all_metadata(self):
        s=schedule();record=s.to_record()
        self.assertEqual(schedule_from_record(json.loads(json.dumps(record))),s)
        self.assertEqual(schedule_from_record(record).fingerprint(),s.fingerprint())
        for altered in (replace(s,source_label='OTHER SOURCE'),replace(s,observed_at_ms=13*H),
                        replace(s,coverage_kind=C.PARTIAL),replace(s,timezone_label='Not/A_Real_Zone')):
            self.assertNotEqual(altered.fingerprint(),s.fingerprint())
        # Unknown zone-shaped labels remain caller metadata, not verified timezone identities.
        self.assertFalse(replace(s,timezone_label='Not/A_Real_Zone').to_record()['timezone_conversion_verified'])

    def test_exact_record_schema_and_false_claims(self):
        base=schedule().to_record()
        cases=[{**base,'extra':1},{k:v for k,v in base.items() if k!='source_label'},
               {**base,'version':'OTHER'},{**base,'coverage_kind':True}]
        for key in ('source_independently_authenticated','timezone_conversion_verified',
                    'trading_eligibility_established','runtime_calendar_enforced'):
            cases.extend(({**base,key:True},{**base,key:0}))
        bad=copy.deepcopy(base);bad['windows'][0]['extra']=1;cases.append(bad)
        for record in cases:
            with self.assertRaises(ValueError):schedule_from_record(record)

    def test_immutability_and_record_mutation_isolation(self):
        s=schedule();fingerprint=s.fingerprint();record=s.to_record()
        with self.assertRaises(FrozenInstanceError):s.schedule_id='CHANGED'
        with self.assertRaises(FrozenInstanceError):s.windows[0].open_ms=0
        record['windows'][0]['open_ms']=0
        self.assertEqual(s.fingerprint(),fingerprint)

    def test_timestamp_presence_is_not_ohlcv_quality_or_trading_authority(self):
        report=assess()
        for key in ('source_independently_authenticated','ohlcv_validated_by_this_assessment',
                    'calendar_instrument_binding_verified','trading_eligibility_established','live_authorized'):
            self.assertIs(report[key],False)
        self.assertEqual(report['schedule_sha256'],schedule().fingerprint())
        changed=assess(observed=(H,2*H,3*H,6*H,7*H))
        self.assertNotEqual(report['observation_times_sha256'],changed['observation_times_sha256'])

    def test_existing_continuous_loader_still_rejects_gaps(self):
        from decimal import Decimal as Decimal
        from ariyan_trading.market_data import Candle,CandleDataset
        bars=tuple(Candle(t,Decimal(1),Decimal(1),Decimal(1),Decimal(1),Decimal(0)) for t in (0,2*H))
        with self.assertRaises(ValueError):
            CandleDataset(bars,'SYNTH',H,'SYNTHETIC',3*H,'0'*64,'canonical','ms')


if __name__=='__main__':unittest.main()
