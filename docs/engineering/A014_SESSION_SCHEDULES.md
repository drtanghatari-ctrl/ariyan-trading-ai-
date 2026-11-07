# A014 — explicit UTC session schedules and observation-time assessment

Based on A013 checkpoint `5d6dd80`. Adds `sessions.py`, twenty-one tests and
this document. Offline declarations only. No existing loader, instrument,
dataset binding, replay, ledger, authorization, demo or CI code is changed.

## Bounded explicit schedule

`SessionWindow(open_ms, close_ms, session_label)` declares a nonempty half-open
UTC millisecond interval. `SessionSchedule` contains an ID, timezone label,
bounded coverage interval, ordered non-overlapping windows, source label and
observation time. Adjacent windows are permitted but never implicitly merged;
split a session around breaks, and provide an overnight window explicitly when
appropriate. Labels can repeat across segments. No session-day assignment or
local trading-date inference is made.

Every window must fit inside `[coverage_start_ms, coverage_end_ms)`. The
schedule contains at most 10,000 windows. Empty schedules are meaningful only
with their explicit coverage declaration:

| Coverage kind | Meaning of an unlisted interval inside coverage |
| --- | --- |
| `CoverageKind.EXHAUSTIVE` | Caller declares that all relevant sessions were listed; a non-overlapping gap is declared closed, still unverified |
| `CoverageKind.PARTIAL` | Only listed sessions are known; gaps remain unknown |

Neither choice independently establishes an exchange's actual schedule.
Outside coverage, all intervals are unknown even for an exhaustive schedule.
There is no extrapolation from weekdays, a last known session, or a calendar ID.

`classify_interval(open_ms, close_ms)` uses exact half-open interval overlap:

| Status | Interpretation relative to the supplied declaration |
| --- | --- |
| `WITHIN_SESSION` | The complete observation interval fits in one listed window |
| `DECLARED_CLOSED` | No overlap, within coverage, and exhaustive coverage declared |
| `UNKNOWN_UNLISTED` | No overlap inside partial coverage |
| `UNKNOWN_OUTSIDE_COVERAGE` | At least part of the interval lies outside coverage |
| `CROSSES_BOUNDARY` | Partial overlap or an interval spanning multiple windows |

These are enum names; serialized values explicitly retain declaration/unknown
language. A bar straddling an opening, closing, break or adjacent-window boundary
is never silently shortened, split or merged. For example, an hourly grid over
a declared 6.5-hour session has a boundary-crossing last interval, not an inferred
short closing bar or automatically missing full bar.

## Timezones, holidays and changes

UTC timestamps are supplied by the caller. `timezone_label` accepts UTC or a
region/name-shaped token; no timezone database lookup, local-time conversion,
ambiguous/nonexistent-time resolution or daylight-saving calculation occurs.
A region/name-shaped label is not proof of a real timezone identity or correct
conversion. Tests with changed UTC offsets are synthetic declarations, not
authoritative exchange/DST fixtures.

Weekends, holidays, early closes, breaks, overnight sessions, venue maintenance
and halt-related changes must be represented in independently verified source
windows if the caller intends to claim an exhaustive schedule. A014 does not
fetch or install such data, discover unexpected closures, verify revisions or
assert that listed sessions actually traded. Missing windows cannot be silently
called holidays when the source coverage is partial.

## Observation timestamp assessment

`assess_observation_times(schedule, observed_opens, *, interval_ms, anchor_ms,
first_open_ms, end_exclusive_ms, as_of_ms)` compares an explicit fixed grid with
the schedule. The grid phase is `(timestamp - anchor_ms) % interval_ms == 0`.
The requested range must contain whole grid intervals and end no later than the
explicit as-of time. Each assessment is limited to 100,000 grid slots and
100,000 observed timestamps; larger horizons require separately scoped queries.
There is no session-relative or automatically changing bar phase.

Observed opens must be a tuple of strictly ordered, unique, aligned timestamps
inside the requested range. Invalid order, duplicates, off-grid values, booleans,
floats, future/incomplete ranges and resource overruns are rejected before a
report. Inputs are never sorted or repaired.

Only full intervals within one listed window are expected session bars. Their
absent opens appear in `missing_session_opens`. Declared closure, unknown and
boundary-crossing slots are counted separately and never become missing session
bars. Observations in those slots are retained with their classifications; they
are not dropped or automatically deemed invalid. The report does not assign a
passing grade. A missing timestamp is relative to the declaration and does not
by itself prove a provider defect or the absence of actual trading.

Timestamp presence is not OHLCV validation, bar completeness, volume quality,
fillability or instrument identity. No prices, volumes, returns, signals or
performance are read or computed. `as_of_ms` establishes the requested bar-end
cutoff only, not source freshness or actual information availability at a past
decision. Observation times on schedule metadata are unsigned caller labels.

## Serialization and fingerprints

`to_record()` returns JSON-compatible data and explicit false authenticity,
timezone-conversion, trading-eligibility and runtime-enforcement flags.
`schedule_from_record()` requires exact keys, version, enum-string coverage
declaration and exact nested window records, including strict timestamp types.
Unknown/missing keys and upgraded claims are rejected. This accepts a dictionary;
there is no JSON-file reader, persistent calendar registry or revision resolver.

Schedule fingerprints are SHA-256 over compact sorted ASCII JSON with the
`ARIYAN-A014-SESSION-SCHEDULE-V1` domain plus NUL. Source labels, observations,
coverage, timezone labels and every window are bound. The observation-time hash
uses `ARIYAN-A014-OBSERVATION-TIMES-V1` plus NUL and records the interval, anchor
and actual ordered observed opens. It is not a full-report, source-byte, price,
or authenticated-capture hash. Query range/as-of and all classifications are
separately retained in the report; there is no report verifier or authority token.

Hashes identify caller-declared content. They do not authenticate the venue,
holiday table, clock, timezone or publication time. An attacker/caller who can
replace all declarations can create another self-consistent schedule.

## Example and integration boundary

```
from ariyan_trading.sessions import (
    CoverageKind, SessionWindow, SessionSchedule, assess_observation_times,
)

# Tiny SYNTHETIC milliseconds, not a production venue calendar.
schedule = SessionSchedule(
    "SYNTHETIC-V1", "UTC", 0, 10000, CoverageKind.EXHAUSTIVE,
    (SessionWindow(1000, 4000, "SYNTHETIC A"),),
    "SYNTHETIC TEST ONLY", 10000,
)
report = assess_observation_times(
    schedule, (1000, 3000), interval_ms=1000, anchor_ms=0,
    first_open_ms=0, end_exclusive_ms=10000, as_of_ms=10000,
)
assert report["missing_session_opens"] == [2000]
```

All fixtures are synthetic. There is no production exchange calendar, holiday
list, halt feed or verified session source. No instrument is automatically
linked by `schedule_id`; A012's `calendar_reference` and timezone are still
caller labels. A013's calendar-verification flag remains false. A007 still
requires continuous epoch-aligned positive-price candles and rejects gaps.
Session-based datasets must not be passed through unchanged A007 replay and
described as validated multi-asset trading.

Next: explicitly bind an instrument, schedule, bar-grid convention and data
source in session-aware intake, preserving closures, unknown coverage and real
missing observations. Product-specific accounting/execution and validation
remain separate work. No live authority or profitability claim follows.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a014.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-one tests cover missing-vs-closed-vs-unknown, partial/outside coverage,
half-open boundaries, breaks/overnight/explicit UTC offset changes, bar anchors,
partial closing bars, adjacent windows, observation retention, malformed input,
resource limits, immutable records/fingerprints and unchanged A007 gap rejection.
The known A006 expected failure remains unresolved.
