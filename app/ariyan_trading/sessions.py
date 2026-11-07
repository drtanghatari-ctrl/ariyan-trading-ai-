"""A014 explicit UTC session declarations; no exchange-calendar truth or trading gate."""
import hashlib
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from enum import Enum

from .instruments import MAX_TIMESTAMP_MS

VERSION = 'ARIYAN-A014-SESSION-SCHEDULE-V1'
MAX_WINDOWS = 10000
MAX_GRID_SLOTS = 100000


class CoverageKind(Enum):
    EXHAUSTIVE = 'CALLER_DECLARES_EXHAUSTIVE_WINDOWS'
    PARTIAL = 'CALLER_DECLARES_PARTIAL_WINDOWS'


class IntervalStatus(Enum):
    WITHIN_SESSION = 'WITHIN_DECLARED_SESSION'
    DECLARED_CLOSED = 'DECLARED_CLOSED_UNVERIFIED'
    UNKNOWN_UNLISTED = 'UNKNOWN_UNLISTED_WINDOW'
    UNKNOWN_OUTSIDE_COVERAGE = 'UNKNOWN_OUTSIDE_DECLARED_COVERAGE'
    CROSSES_BOUNDARY = 'CROSSES_DECLARED_SESSION_BOUNDARY'


def _time(value):
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        raise ValueError('Bounded integer millisecond timestamp required')


def _label(value, maximum):
    if (type(value) is not str or not value or value != value.strip() or len(value) > maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid bounded text label')


def _encoded(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


@dataclass(frozen=True)
class SessionWindow:
    open_ms: int
    close_ms: int
    session_label: str

    def __post_init__(self):
        _time(self.open_ms); _time(self.close_ms)
        if self.close_ms <= self.open_ms:
            raise ValueError('Session window must be nonempty and half open')
        _label(self.session_label, 128)

    def to_record(self):
        return {'open_ms': self.open_ms, 'close_ms': self.close_ms,
                'session_label': self.session_label}


@dataclass(frozen=True)
class SessionSchedule:
    schedule_id: str
    timezone_label: str
    coverage_start_ms: int
    coverage_end_ms: int
    coverage_kind: CoverageKind
    windows: tuple
    source_label: str
    observed_at_ms: int
    _opens: tuple = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        _label(self.schedule_id, 128)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', self.schedule_id):
            raise ValueError('Invalid schedule ID token')
        _label(self.timezone_label, 80)
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', self.timezone_label):
            raise ValueError('Invalid timezone label')
        if self.timezone_label != 'UTC' and '/' not in self.timezone_label:
            raise ValueError('Timezone label must be UTC or region/name; no abbreviation')
        _time(self.coverage_start_ms); _time(self.coverage_end_ms); _time(self.observed_at_ms)
        if self.coverage_end_ms <= self.coverage_start_ms:
            raise ValueError('Declared coverage interval must be nonempty')
        if type(self.coverage_kind) is not CoverageKind:
            raise ValueError('Explicit coverage-kind enum required')
        if type(self.windows) is not tuple or len(self.windows) > MAX_WINDOWS:
            raise ValueError('Bounded tuple of session windows required')
        _label(self.source_label, 2048)
        previous_close = self.coverage_start_ms
        for window in self.windows:
            if type(window) is not SessionWindow:
                raise ValueError('SessionWindow objects required')
            if window.open_ms < previous_close or window.close_ms > self.coverage_end_ms:
                raise ValueError('Windows must be ordered, disjoint and inside declared coverage')
            previous_close = window.close_ms
        object.__setattr__(self, '_opens', tuple(w.open_ms for w in self.windows))

    def classify_interval(self, open_ms, close_ms):
        """Classify [open, close) against declarations, never actual trading eligibility."""
        _time(open_ms); _time(close_ms)
        if close_ms <= open_ms:
            raise ValueError('Nonempty observation interval required')
        if open_ms < self.coverage_start_ms or close_ms > self.coverage_end_ms:
            return IntervalStatus.UNKNOWN_OUTSIDE_COVERAGE
        index = bisect_right(self._opens, open_ms) - 1
        if index >= 0 and self.windows[index].close_ms >= close_ms:
            return IntervalStatus.WITHIN_SESSION
        if ((index >= 0 and self.windows[index].close_ms > open_ms)
                or index + 1 < len(self.windows) and self.windows[index + 1].open_ms < close_ms):
            return IntervalStatus.CROSSES_BOUNDARY
        return (IntervalStatus.DECLARED_CLOSED if self.coverage_kind is CoverageKind.EXHAUSTIVE
                else IntervalStatus.UNKNOWN_UNLISTED)

    def to_record(self):
        return {'version': VERSION, 'schedule_id': self.schedule_id,
                'timezone_label': self.timezone_label,
                'coverage_start_ms': self.coverage_start_ms, 'coverage_end_ms': self.coverage_end_ms,
                'coverage_kind': self.coverage_kind.value,
                'windows': [w.to_record() for w in self.windows],
                'source_label': self.source_label, 'observed_at_ms': self.observed_at_ms,
                'source_independently_authenticated': False, 'timezone_conversion_verified': False,
                'trading_eligibility_established': False, 'runtime_calendar_enforced': False}

    def fingerprint(self):
        return hashlib.sha256(b'ARIYAN-A014-SESSION-SCHEDULE-V1\0' + _encoded(self.to_record())).hexdigest()


def schedule_from_record(record):
    keys = {'version','schedule_id','timezone_label','coverage_start_ms','coverage_end_ms',
            'coverage_kind','windows','source_label','observed_at_ms','source_independently_authenticated',
            'timezone_conversion_verified','trading_eligibility_established','runtime_calendar_enforced'}
    if type(record) is not dict or set(record) != keys or record['version'] != VERSION:
        raise ValueError('Exact supported session-schedule record required')
    for key in ('source_independently_authenticated','timezone_conversion_verified',
                'trading_eligibility_established','runtime_calendar_enforced'):
        if record[key] is not False:
            raise ValueError('Unsupported authenticity/conversion/eligibility/enforcement claim')
    if type(record['windows']) is not list or len(record['windows']) > MAX_WINDOWS:
        raise ValueError('Bounded window array required')
    windows = []
    for row in record['windows']:
        if type(row) is not dict or set(row) != {'open_ms','close_ms','session_label'}:
            raise ValueError('Exact session window record required')
        windows.append(SessionWindow(**row))
    if type(record['coverage_kind']) is not str:
        raise ValueError('Coverage kind record value must be a string')
    return SessionSchedule(record['schedule_id'],record['timezone_label'],record['coverage_start_ms'],
        record['coverage_end_ms'],CoverageKind(record['coverage_kind']),tuple(windows),
        record['source_label'],record['observed_at_ms'])


def assess_observation_times(schedule, observed_opens, *, interval_ms, anchor_ms,
                             first_open_ms, end_exclusive_ms, as_of_ms):
    """Compare timestamp availability with a bounded explicit grid and schedule.

    No OHLC, price/volume, instrument mapping, local-time conversion or replay.
    Unknown/closure/boundary slots are never counted as missing session bars.
    """
    if type(schedule) is not SessionSchedule:
        raise ValueError('SessionSchedule required')
    # Revalidate the schedule record instead of trusting cached search indexes.
    schedule = schedule_from_record(schedule.to_record())
    for timestamp in (anchor_ms,first_open_ms,end_exclusive_ms,as_of_ms):
        _time(timestamp)
    if type(interval_ms) is not int or not 1 <= interval_ms <= MAX_TIMESTAMP_MS:
        raise ValueError('Positive bounded integer interval required')
    if not first_open_ms < end_exclusive_ms <= as_of_ms:
        raise ValueError('Requested intervals must be complete by explicit as-of time')
    if (first_open_ms-anchor_ms) % interval_ms or (end_exclusive_ms-first_open_ms) % interval_ms:
        raise ValueError('Requested range must fit the explicit whole-bar grid')
    slots = (end_exclusive_ms-first_open_ms) // interval_ms
    if slots > MAX_GRID_SLOTS:
        raise ValueError('Requested grid exceeds supported slot count')
    if type(observed_opens) is not tuple or len(observed_opens) > MAX_GRID_SLOTS:
        raise ValueError('Bounded tuple of observed timestamps required')
    previous = None
    for opened in observed_opens:
        _time(opened)
        if (not first_open_ms <= opened < end_exclusive_ms
                or (opened-anchor_ms) % interval_ms
                or previous is not None and opened <= previous):
            raise ValueError('Observed timestamps must be in range, on grid and strictly ordered')
        previous = opened
    seen = set(observed_opens)
    expected = []; missing = []; non_session_observations = []
    counts = {status.value: 0 for status in IntervalStatus}
    for opened in range(first_open_ms,end_exclusive_ms,interval_ms):
        status = schedule.classify_interval(opened,opened+interval_ms)
        counts[status.value] += 1
        if status is IntervalStatus.WITHIN_SESSION:
            expected.append(opened)
            if opened not in seen:
                missing.append(opened)
        elif opened in seen:
            non_session_observations.append({'open_ms':opened,'classification':status.value})
    observed_hash = hashlib.sha256(b'ARIYAN-A014-OBSERVATION-TIMES-V1\0' + _encoded({
        'interval_ms':interval_ms,'anchor_ms':anchor_ms,'observed_opens':list(observed_opens)})).hexdigest()
    return {'version':'ARIYAN-A014-SESSION-TIME-ASSESSMENT-V1',
            'schedule':schedule.to_record(),'schedule_sha256':schedule.fingerprint(),
            'grid':{'interval_ms':interval_ms,'anchor_ms':anchor_ms,
                    'first_open_ms':first_open_ms,'end_exclusive_ms':end_exclusive_ms,'as_of_ms':as_of_ms},
            'observed_opens':list(observed_opens),'observation_times_sha256':observed_hash,
            'grid_slot_counts':counts,'expected_session_opens':expected,'missing_session_opens':missing,
            'observed_session_bars':len(expected)-len(missing),
            'observations_outside_full_declared_sessions':non_session_observations,
            'source_independently_authenticated':False,'ohlcv_validated_by_this_assessment':False,
            'calendar_instrument_binding_verified':False,'trading_eligibility_established':False,
            'live_authorized':False,
            'limitations':[
                'Session windows and exhaustive coverage are caller assertions, not exchange-calendar truth.',
                'Unknown, declared closure and boundary-crossing slots do not prove a provider defect.',
                'Missing session timestamps are relative to declarations, not independent data-quality certification.',
                'No local-time/DST/holiday computation, halt feed, early-close discovery or revision verification.',
                'No bars are shortened, added, sorted, compressed, imputed or repaired.',
                'Timestamp presence does not validate OHLCV, volume, instrument terms or fillability.',
                'A007/A013/replay are unchanged; this assessment is not a runtime or authorization gate.']}
