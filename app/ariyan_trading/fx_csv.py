"""A041 offline importer for forex/CFD candle CSV exports (Stooq, Yahoo, Dukascopy, MT5, canonical).

No network. Reads one local file and returns a validated `SessionCandleDataset` plus a
report of everything that was skipped, dropped or split. Nothing is repaired or invented:

- Timestamps are never guessed. Naive times are read in the zone the caller states
  (`timezone_name` or `utc_offset_minutes`, default UTC). MT5 server times are usually
  GMT+2/+3 and the caller must say which.
- Bars outside the declared session (for example a Saturday bar) are dropped and counted.
- A gap inside a declared session is never filled. By default the importer keeps the
  longest gap-free run and reports the rest; `keep_longest_run=False` raises instead.
- The last bar is dropped by default because downloads often end with an unfinished bar.
- Daily bars are labelled by date and treated as the UTC calendar day, Monday to Friday.
  Providers cut FX days at different times, so daily alignment is approximate.
Sessions are caller declarations, not exchange-calendar truth: holidays are not known.
"""
import csv
import hashlib
import io
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .market_data import Candle, MAX_BYTES, MAX_ROWS, number
from .session_candles import SessionCandleDataset, daily_session_schedule, weekly_session_schedule
from .sessions import IntervalStatus

DAY_MS = 86_400_000
MAX_SLOTS_PER_GAP = 50_000
_ACCEPTED = (IntervalStatus.WITHIN_SESSION, IntervalStatus.CROSSES_BOUNDARY)
_TS_NAMES = {'timestamp', 'timestamp_ms', 'datetime', 'gmt time', 'local time', 'time (utc)', 'utc time'}
_VOLUME_NAMES = ('volume', 'vol', 'tickvol', 'tick volume', 'tick_volume')
_FORMATS = ('%Y.%m.%d %H:%M:%S', '%Y.%m.%d %H:%M', '%Y.%m.%d', '%d.%m.%Y %H:%M:%S.%f',
            '%d.%m.%Y %H:%M:%S', '%d.%m.%Y %H:%M', '%d.%m.%Y', '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y %H:%M', '%m/%d/%Y', '%Y/%m/%d %H:%M:%S', '%Y/%m/%d')


@dataclass(frozen=True)
class ImportReport:
    rows_read: int
    skipped_rows: tuple            # ((line_number, reason), ...) when on_bad_row='skip'
    dropped_outside_session: int
    dropped_last_candle: bool
    truncated_to_recent: int       # older candles discarded to respect the 100,000 limit
    runs: tuple                    # ((first_ms, last_ms, count), ...) gap-free runs found
    kept_run: tuple                # (first_ms, last_ms, count)
    interval_ms: int
    raw_sha256: str


def _zone(timezone_name, utc_offset_minutes):
    if timezone_name is not None and utc_offset_minutes is not None:
        raise ValueError('Give timezone_name or utc_offset_minutes, not both')
    if timezone_name is not None:
        try:
            return ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
            raise ValueError('Unknown timezone: %s' % timezone_name) from exc
    if utc_offset_minutes is None:
        return timezone.utc
    if type(utc_offset_minutes) is not int or abs(utc_offset_minutes) > 14 * 60:
        raise ValueError('utc_offset_minutes must be an integer within +/-840')
    return timezone(timedelta(minutes=utc_offset_minutes))


def _parse_time(text, zone, epoch_only=False):
    text = text.strip().strip('"')
    if re.fullmatch(r'[0-9]{9,10}', text):
        return int(text) * 1000
    if re.fullmatch(r'[0-9]{12,13}', text):
        return int(text)
    if epoch_only:
        raise ValueError('Epoch timestamp must be 10 digits (s) or 13 digits (ms)')
    parsed = None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        for fmt in _FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        raise ValueError('Unrecognised time %r' % text[:40])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=zone)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def _columns(header):
    names = [re.sub(r'[<>"]', '', h).strip().lower() for h in header]
    found = {}
    for index, name in enumerate(names):
        if name == 'timestamp_ms':
            found['ts_ms'] = index
        elif name in _TS_NAMES:
            found.setdefault('ts', index)
        elif name == 'date':
            found.setdefault('date', index)
        elif name == 'time':
            found.setdefault('time', index)
        elif name in ('open', 'high', 'low', 'close'):
            found.setdefault(name, index)
        elif name in _VOLUME_NAMES:
            found.setdefault('volume', index)
    if 'ts_ms' not in found and 'ts' not in found and 'date' not in found:
        if 'time' in found:
            found['ts'] = found.pop('time')
        else:
            raise ValueError('No date/time column found in header')
    for name in ('open', 'high', 'low', 'close'):
        if name not in found:
            raise ValueError('Header has no %s column' % name)
    return found


def _decimal(text, name):
    try:
        value = Decimal(text.strip())
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise ValueError('%s is not a number: %r' % (name, text[:20])) from exc
    if not value.is_finite():
        raise ValueError('%s is not finite' % name)
    return value


def _parse_rows(raw, zone, on_bad_row):
    text = raw.decode('utf-8-sig')
    sample = text[:4096].splitlines()[0] if text.strip() else ''
    delimiter = '\t' if '\t' in sample else ';' if sample.count(';') > sample.count(',') else ','
    reader = csv.reader(io.StringIO(text, newline=''), delimiter=delimiter)
    header = next(reader, None)
    if header is None:
        raise ValueError('Empty file')
    cols = _columns(header)
    candles, skipped, rows = [], [], 0
    for row in reader:
        if not row or not any(cell.strip() for cell in row):
            continue
        rows += 1
        line = reader.line_num
        try:
            if 'ts_ms' in cols:
                stamp = _parse_time(row[cols['ts_ms']], zone, epoch_only=True)
            elif 'ts' in cols:
                stamp = _parse_time(row[cols['ts']], zone)
            else:
                clock = row[cols['time']].strip() if 'time' in cols and cols['time'] < len(row) else ''
                stamp = _parse_time((row[cols['date']].strip() + ' ' + clock).strip(), zone)
            values = [_decimal(row[cols[n]], n) for n in ('open', 'high', 'low', 'close')]
            volume = Decimal(0)
            if 'volume' in cols and cols['volume'] < len(row) and row[cols['volume']].strip():
                volume = _decimal(row[cols['volume']], 'volume')
            if stamp % 1000:
                raise ValueError('Timestamp is not whole seconds')
            candles.append(Candle(stamp, *[number(v, n) for v, n in zip(values, ('open', 'high', 'low', 'close'))],
                                  number(volume, 'volume', allow_zero=True)))
        except (ValueError, IndexError, TypeError) as exc:
            if on_bad_row == 'raise':
                raise ValueError('CSV line %d: %s' % (line, exc)) from exc
            skipped.append((line, str(exc)))
    return candles, tuple(skipped), rows


def _runs(candles, interval_ms, schedule):
    runs = [[candles[0]]]
    for candle in candles[1:]:
        previous = runs[-1][-1].timestamp_ms
        slots = (candle.timestamp_ms - previous) // interval_ms - 1
        ok = slots <= MAX_SLOTS_PER_GAP and all(
            schedule.classify_interval(s, s + interval_ms) is IntervalStatus.DECLARED_CLOSED
            for s in range(previous + interval_ms, candle.timestamp_ms, interval_ms))
        if ok:
            runs[-1].append(candle)
        else:
            runs.append([candle])
    return runs


def load_fx_csv(path, *, symbol, source, interval_ms=None, timezone_name=None, utc_offset_minutes=None,
                on_bad_row='raise', keep_longest_run=True, drop_last_candle=True, schedule=None,
                as_of_ms=None):
    """Return (SessionCandleDataset, ImportReport). Raises ValueError on anything unusable.

    interval_ms: bar length; inferred from the most common spacing when omitted.
    schedule: optional SessionSchedule (e.g. an equity session); otherwise forex defaults are
    built: weekly Sunday 17:00 to Friday 17:00 New York for intraday bars, Monday-Friday UTC days
    for daily bars. Intervals above one day are unsupported.
    """
    if on_bad_row not in ('raise', 'skip'):
        raise ValueError("on_bad_row must be 'raise' or 'skip'")
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('CSV exceeds the 32 MiB input limit')
    digest = hashlib.sha256(raw).hexdigest()
    candles, skipped, rows = _parse_rows(raw, _zone(timezone_name, utc_offset_minutes), on_bad_row)
    candles.sort(key=lambda c: c.timestamp_ms)
    for earlier, later in zip(candles, candles[1:]):
        if earlier.timestamp_ms == later.timestamp_ms:
            raise ValueError('Duplicate timestamp %d' % later.timestamp_ms)
    if len(candles) < 3:
        raise ValueError('Too few usable candles (%d)' % len(candles))
    if interval_ms is None:
        interval_ms = Counter(b.timestamp_ms - a.timestamp_ms
                              for a, b in zip(candles, candles[1:])).most_common(1)[0][0]
    if type(interval_ms) is not int or interval_ms < 1000 or interval_ms > DAY_MS:
        raise ValueError('interval_ms must be between one second and one day')
    dropped_last = False
    if drop_last_candle:
        candles, dropped_last = candles[:-1], True
    if as_of_ms is None:
        as_of_ms = candles[-1].timestamp_ms + interval_ms
    if schedule is None:
        first = datetime.fromtimestamp(candles[0].timestamp_ms / 1000, timezone.utc).date() - timedelta(days=8)
        last = datetime.fromtimestamp(candles[-1].timestamp_ms / 1000, timezone.utc).date() + timedelta(days=8)
        label = 'IMPORTED-FX-DEFAULT-SESSIONS (caller declaration, no holidays)'
        if interval_ms == DAY_MS:
            schedule = daily_session_schedule('IMPORTED-FX-DAILY', 'UTC', (0, 1, 2, 3, 4), time(0), time(23, 59, 59),
                                              first, last, label, as_of_ms)
        else:
            schedule = weekly_session_schedule('IMPORTED-FX-WEEKLY', 'America/New_York', 6, time(17), 4, time(17),
                                               first, last, label, as_of_ms)
    inside = [c for c in candles
              if schedule.classify_interval(c.timestamp_ms, c.timestamp_ms + interval_ms) in _ACCEPTED]
    dropped_outside = len(candles) - len(inside)
    if len(inside) < 2:
        raise ValueError('Fewer than two candles fall inside the declared sessions')
    truncated = max(0, len(inside) - MAX_ROWS)
    inside = inside[truncated:]
    runs = _runs(inside, interval_ms, schedule)
    if len(runs) > 1 and not keep_longest_run:
        raise ValueError('%d gap-free runs found; gaps inside declared sessions (first break near %d)'
                         % (len(runs), runs[1][0].timestamp_ms))
    best = max(runs, key=len)
    if len(best) < 2:
        raise ValueError('No gap-free run of at least two candles')
    dataset = SessionCandleDataset(tuple(best), symbol, interval_ms, source, as_of_ms, digest, schedule,
                                   best[0].timestamp_ms % interval_ms)
    summary = tuple((r[0].timestamp_ms, r[-1].timestamp_ms, len(r)) for r in runs)
    report = ImportReport(rows, skipped, dropped_outside, dropped_last, truncated, summary,
                          (best[0].timestamp_ms, best[-1].timestamp_ms, len(best)), interval_ms, digest)
    return dataset, report
