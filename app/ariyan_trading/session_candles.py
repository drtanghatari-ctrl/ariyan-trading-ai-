"""A037 candle datasets with validated session closures, plus schedule builders.

A007 `CandleDataset` rejects every gap. Forex weekends, stock overnights and
holidays are legitimate gaps. `SessionCandleDataset` accepts a gap only when
every missing grid slot lies outside the caller's declared session windows;
a missing slot inside a declared session is still rejected, never repaired.
Schedules are caller declarations, not exchange-calendar truth: holidays and
early closes must be supplied by the caller.
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .market_data import Candle, MAX_ROWS, integer
from .sessions import CoverageKind, IntervalStatus, SessionSchedule, SessionWindow

MAX_MISSING_SLOTS = 2_000_000
_ACCEPTED_OBSERVED = (IntervalStatus.WITHIN_SESSION, IntervalStatus.CROSSES_BOUNDARY)


@dataclass(frozen=True)
class SessionCandleDataset:
    candles: tuple
    symbol: str
    interval_ms: int
    source: str
    as_of_ms: int
    raw_sha256: str
    schedule: SessionSchedule
    anchor_ms: int = 0

    def __post_init__(self):
        integer(self.interval_ms, 'interval_ms', 1)
        integer(self.as_of_ms, 'as_of_ms')
        integer(self.anchor_ms, 'anchor_ms')
        if not isinstance(self.symbol, str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9_.:/-]{0,39}', self.symbol):
            raise ValueError('Invalid symbol label')
        if not isinstance(self.source, str) or not self.source.strip() or len(self.source) > 2048:
            raise ValueError('A nonempty source label is required')
        if not isinstance(self.raw_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', self.raw_sha256):
            raise ValueError('Invalid input SHA256')
        if type(self.schedule) is not SessionSchedule:
            raise ValueError('SessionSchedule required')
        if type(self.candles) is not tuple or not 2 <= len(self.candles) <= MAX_ROWS:
            raise ValueError('Dataset requires 2..%d candles' % MAX_ROWS)
        previous = None
        missing = 0
        for candle in self.candles:
            if type(candle) is not Candle:
                raise ValueError('Dataset contains a non-Candle object')
            if (candle.timestamp_ms - self.anchor_ms) % self.interval_ms:
                raise ValueError('Candle is not aligned to the interval grid')
            if previous is not None:
                if candle.timestamp_ms <= previous:
                    raise ValueError('Duplicate or unordered candle')
                for slot in range(previous + self.interval_ms, candle.timestamp_ms, self.interval_ms):
                    missing += 1
                    if missing > MAX_MISSING_SLOTS:
                        raise ValueError('Too many missing slots to verify')
                    status = self.schedule.classify_interval(slot, slot + self.interval_ms)
                    if status is not IntervalStatus.DECLARED_CLOSED:
                        # Only a slot the schedule positively declares closed may be absent;
                        # in-session, boundary-crossing, unlisted or out-of-coverage slots may not.
                        raise ValueError('Missing candle at %d is not a declared closure (%s)'
                                         % (slot, status.value))
            status = self.schedule.classify_interval(candle.timestamp_ms,
                                                     candle.timestamp_ms + self.interval_ms)
            if status not in _ACCEPTED_OBSERVED:
                raise ValueError('Candle observed outside a declared session at %d' % candle.timestamp_ms)
            if candle.timestamp_ms + self.interval_ms > self.as_of_ms:
                raise ValueError('Dataset includes an incomplete/future candle')
            previous = candle.timestamp_ms


def slice_dataset(dataset, start, end):
    """Return candles[start:end] as the same dataset type, keeping parent provenance.

    The recorded hash still identifies the full original input bytes.
    """
    from .market_data import CandleDataset
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(dataset.candles):
        raise ValueError('Invalid slice bounds')
    window = dataset.candles[start:end]
    if type(dataset) is CandleDataset:
        return CandleDataset(window, dataset.symbol, dataset.interval_ms, dataset.source,
                             dataset.as_of_ms, dataset.raw_sha256, dataset.input_format,
                             dataset.timestamp_unit)
    if type(dataset) is SessionCandleDataset:
        return SessionCandleDataset(window, dataset.symbol, dataset.interval_ms, dataset.source,
                                    dataset.as_of_ms, dataset.raw_sha256, dataset.schedule,
                                    dataset.anchor_ms)
    raise ValueError('Unsupported dataset type')


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValueError('Unknown timezone: %s' % name) from exc


def _utc_ms(day, clock, zone):
    local = datetime.combine(day, clock, tzinfo=zone)
    return int(local.astimezone(timezone.utc).timestamp() * 1000)


def _dates(start, end):
    if type(start) is not date or type(end) is not date or end < start:
        raise ValueError('Valid inclusive start/end dates required')
    if (end - start).days > 20_000:
        raise ValueError('Date range too long')
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def _finish(schedule_id, timezone_name, windows, start, end, source_label, observed_at_ms):
    zone = _zone(timezone_name)
    coverage_start = _utc_ms(start, time(0), zone)
    coverage_end = _utc_ms(end + timedelta(days=1), time(0), zone)
    clipped = []
    for open_ms, close_ms, label in windows:
        open_ms, close_ms = max(open_ms, coverage_start), min(close_ms, coverage_end)
        if close_ms > open_ms:
            clipped.append(SessionWindow(open_ms, close_ms, label))
    clipped.sort(key=lambda w: w.open_ms)
    return SessionSchedule(schedule_id, timezone_name, coverage_start, coverage_end,
                           CoverageKind.EXHAUSTIVE, tuple(clipped), source_label, observed_at_ms)


def daily_session_schedule(schedule_id, timezone_name, weekdays, open_time, close_time,
                           start_date, end_date, source_label, observed_at_ms,
                           holidays=(), early_closes=None):
    """Exchange-style sessions: local open/close on selected weekdays (Mon=0 .. Sun=6).

    Local times are converted with the IANA database (DST aware). `holidays` are
    caller-supplied closed dates; `early_closes` maps a date to its local close time.
    """
    zone = _zone(timezone_name)
    holidays, early_closes = set(holidays), dict(early_closes or {})
    if not weekdays or any(type(d) is not int or not 0 <= d <= 6 for d in weekdays):
        raise ValueError('weekdays must be integers 0..6')
    if type(open_time) is not time or type(close_time) is not time or close_time <= open_time:
        raise ValueError('Same-day open_time < close_time required')
    windows = []
    for day in _dates(start_date, end_date):
        if day.weekday() not in weekdays or day in holidays:
            continue
        close = early_closes.get(day, close_time)
        if type(close) is not time or close <= open_time:
            raise ValueError('Invalid early close for %s' % day)
        windows.append((_utc_ms(day, open_time, zone), _utc_ms(day, close, zone),
                        'DAILY-' + day.isoformat()))
    return _finish(schedule_id, timezone_name, windows, start_date, end_date, source_label, observed_at_ms)


def weekly_session_schedule(schedule_id, timezone_name, open_weekday, open_time, close_weekday,
                            close_time, start_date, end_date, source_label, observed_at_ms,
                            holidays=()):
    """Continuous weekly session, e.g. forex: Sunday 17:00 to Friday 17:00 New York.

    The window opens on `open_weekday` at `open_time` and closes at the next
    `close_weekday` at `close_time` (local, DST aware). Opens on `holidays` dates
    are skipped.
    """
    zone = _zone(timezone_name)
    holidays = set(holidays)
    for value in (open_weekday, close_weekday):
        if type(value) is not int or not 0 <= value <= 6:
            raise ValueError('weekdays must be integers 0..6')
    if type(open_time) is not time or type(close_time) is not time:
        raise ValueError('time objects required')
    windows = []
    for day in _dates(start_date - timedelta(days=8), end_date):
        if day.weekday() != open_weekday or day in holidays:
            continue
        gap = (close_weekday - open_weekday) % 7
        close_day = day + timedelta(days=gap)
        if gap == 0 and close_time <= open_time:
            close_day += timedelta(days=7)
        windows.append((_utc_ms(day, open_time, zone), _utc_ms(close_day, close_time, zone),
                        'WEEKLY-' + day.isoformat()))
    return _finish(schedule_id, timezone_name, windows, start_date, end_date, source_label, observed_at_ms)
