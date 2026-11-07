# A015 — session-aware canonical candle intake

Based on A014 checkpoint `5a9b41d`. Adds `session_data.py`, twenty-one tests and
this document. Existing A007/A011 intake, A012 terms, A013 bindings, A014
schedules, replay, ledger, authorization, demo and CI implementations are
unchanged. No market performance, strategy selection or live action occurs.

## Scope

`load_session_candles(...)` reads bounded canonical CSV into a distinct immutable
`SessionCandleSeries`. Its candles retain native timestamps and can have gaps,
including scheduled closures or missing observations. It is not an A007
`CandleDataset`, and A007 `run_replay()` explicitly rejects the distinct type.
There is no automatic conversion to a continuous replay dataset.

Inputs are explicit: caller symbol/source/mapping labels, an A012 instrument,
an A014 UTC schedule, fixed bar interval/anchor, requested first-open/end bounds,
as-of cutoff, raw price-basis declaration and volume unit. No default production
instrument, current venue specification, exchange calendar or provider mapping
is installed or inferred from the display ticker.

## Preconditions and parsing

The instrument's calendar reference and timezone label must exactly match the
schedule ID and timezone label. This checks declared reference consistency,
not independent calendar/instrument truth. Both objects and every schedule
window are revalidated before input I/O. A014 validates the whole fixed grid,
as-of cutoff and resource bounds. Unknown schedule coverage remains permitted
and explicitly classified; there is no extrapolation from partial schedules.

One instrument definition must cover the entire requested interval, including
closed or missing slots. Futures queries must end no later than the declared
last trade. This prevents expected-bar checks outside the definition's stated
life; it is not an order-admission or contract-valuation implementation.

Only `RAW_UNADJUSTED_SINGLE_INSTRUMENT` is supported. Volume units must explicitly
equal the instrument's quantity unit. Both declarations remain caller assertions.
No adjusted equity series, continuous/rolled futures, composites, currency/unit
conversion or action/roll provenance is inferred or repaired.

The input must have the exact canonical six-column header:

```
timestamp_ms,open,high,low,close,volume
```

UTF-8/BOM handling and basic numeric/OHLC validation follow A007. The entire
file is bounded to 32 MiB and 100,000 candles. OHLC values must be positive,
finite, bounded and internally consistent; volume must be nonnegative. All
OHLC fields must also lie on the declared instrument price grid. Prices are
never rounded/snapped to fit. Aggregate volume is not an order quantity and
is not tested against the order minimum or lot grid. Zero volume is retained.

Every supplied timestamp must be on the explicit grid, unique, strictly ordered,
inside the requested interval and closed by the as-of cutoff. Off-grid, duplicate,
unordered, malformed, out-of-range and future/incomplete inputs reject the
entire source. There is no row quarantine or partial-success result in A015.
Input files are never modified, and symlink parent/file paths are not followed.

Header-only and singleton files are valid intake evidence: an empty series can
report every declared session timestamp as missing, rather than inventing bars.
An empty file without the header is rejected. These behaviours do not establish
a usable trading sample or source-quality grade.

## What is retained and reported

All structurally valid supplied candles are retained in `series.candles`, even
when their full interval is classified as declared closed, unknown or crossing
a session boundary. Those observations appear separately in the nested A014
assessment. A015 does not silently exclude them or assert they are provider
errors. Boundary-crossing bars are not split, shortened or relabelled.

Only missing complete intervals inside one declared session become
`missing_session_opens`. Scheduled closures, unknown coverage and crossing
intervals remain distinct. Gaps are not forward filled, compressed, sorted,
repaired or joined across sessions. Partial schedules cannot certify unlisted
times as closed. No passing grade or calendar-verification claim is assigned.

`to_report()` records full instrument terms/fingerprints, matching declaration
labels, source/provenance information, bar count, canonical candle-content hash
and the full A014 timestamp assessment. Basic row validation is a separate
statement; the nested timestamp assessment's OHLCV flag remains false because
that A014 component itself only checks timestamps.

The loader's `raw_sha256` hashes the exact canonical CSV bytes read once,
including formatting/BOM. This may describe a derived canonical file rather
than the provider's original archive. A manually constructed or derived series
can carry a caller-supplied/inherited raw hash; it is not proof of subset bytes.

The canonical content hash binds EVERY supplied row (including outside-session
observations), interval and count, using the A013 canonical numeric spelling
policy and the `ARIYAN-A015-CANDLE-CONTENT-V1` domain plus NUL. Equivalent numeric
spellings can share a value hash while their source-byte hashes differ. Selecting
a subset or changing OHLCV changes the value hash even if an inherited raw hash
is unchanged. A015 does not identify these hashes as A013 binding hashes.

`intake_sha256` covers every other report field with compact sorted ASCII JSON
and domain `ARIYAN-A015-INTAKE-V1` plus NUL. `verify_session_report(series, report)`
rebuilds and compares all fields with JSON type-sensitive encoding, rejecting
changed terms, mappings, rows, metadata, flags, unknown/missing fields and stale
hashes. Reports omit full candle arrays; the series retains them in memory.
There is no report-file reader/writer, persistent registry or authenticated
publication anchor in this module.

These are unsigned content identifiers and supplied-object consistency checks,
not independent venue/calendar truth, source authenticity or point-in-time
availability. Replacing all inputs and rebuilding can produce another consistent
report. Source capture/effective times are caller labels, not proof that past
decisions had access to the stated information.

## API workflow and limitations

```
from ariyan_trading.instrument_data import PRICE_BASIS
from ariyan_trading.session_data import load_session_candles, verify_session_report

# Establish spec, schedule, dates and units independently before intake.
series = load_session_candles(
    "work/candles.csv", symbol=declared_symbol, source=source_label,
    spec=spec, schedule=schedule, interval_ms=interval_ms, anchor_ms=anchor_ms,
    first_open_ms=first_open_ms, end_exclusive_ms=end_exclusive_ms, as_of_ms=as_of_ms,
    price_basis=PRICE_BASIS, volume_unit=spec.quantity_unit,
    mapping_source="Caller mapping record; independent verification pending",
)
report = series.to_report()
verify_session_report(series, report)
```

A012 SIGNED/NONNEGATIVE domains do not enable zero/negative OHLC candles here;
the reused positive-price Candle model still applies. Signed-price intake needs
a separate validated model and accounting/execution work. No corporate actions,
roll calculation, margin, position handling across missing prices, currency PnL,
session-aware feature windows or session-aware replay is implemented. No stock,
metal, oil or derivative trading readiness follows from representable metadata.

Tests are synthetic except an existing real BTC 24-bar fixture converted to
canonical CSV for integration smoke. Its attached terms/calendar are explicitly
synthetic, not authenticated venue data. No performance is computed. Existing
research outputs and reserved-performance boundaries remain unchanged.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a015.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-one tests cover native gaps, missing-vs-closed/unknown/boundary distinctions,
outside-session retention, empty/singleton evidence, non-epoch grids, reference
matching, effective/last-trade bounds, byte/value/subset hashing, strict CSV/OHLCV,
volume semantics, source/resource/time restrictions, immutable reports, context
isolation, unchanged A007 rejection and real-fixture conversion smoke.
The known A006 expected failure remains unresolved.
