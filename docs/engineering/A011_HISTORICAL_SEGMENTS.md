# A011 — explicit historical exclusions and contiguous coverage

Base: 3c38779 (A010). Adds historical_segments.py, its tests, this document and
a small derived real-data fixture/provenance. Existing app modules, ledger,
authorization, default demo and CI are unchanged. No network or live orders.

## Source problem found while expanding R003 history

February 2021 BTCUSDT, ETHUSDT and SOLUSDT monthly ZIP checksums matched, but
all three fail strict A010 intake. Each source has 671 rows for 672 hourly slots:
row 244 opens at 2021-02-11 03:00 UTC with an early native close, and 04:00 is
absent before the next published row at 05:00. This leaves 670 complete rows,
one excluded partial row and one missing hour. Two complete spans contain
243 and 427 rows. Matching checksums establish transfer consistency, not coverage.

A contributor on Binance's public-data repository notes that some missing klines
reflect server maintenance and that the archives follow its API. That general
explanation does not prove the cause of every row in these sources:
https://github.com/binance/binance-public-data/issues/77

Do not invent the absent hour or extend a partial row. A007/A010 correctly reject
such input under their continuous/full-month contracts. A011 is a separate
quality/training coverage index; it does not admit the whole source for replay.

## API and policy

inspect_history(path, symbol=..., source=..., interval_ms=..., as_of_ms=...,
timestamp_unit="ms") reads bounded headerless twelve-column spot CSV. Original
bytes are hashed unchanged. Opens must be exact milliseconds on an epoch-aligned,
strictly increasing grid. Explicit ms/us conversion is supported without guessing.
There is no sorting, interpolation, padding, resampling, retiming or time compression.

Structural problems reject the entire intake: wrong field count, empty input,
unlocatable/misaligned/duplicate/unordered opens, future source slots, bad labels/
units and the existing 32 MiB/100,000-row limits. The entire expected slot must be
closed at the explicit cutoff even if the native row ends early.

On a valid open grid, rows are excluded with explicit line/time/reason records:

- PARTIAL_INTERVAL: close is at/after open and before the expected interval end.
- INVALID_CLOSE_TIME: close is unparseable, before open, or after expected end.
- INVALID_OHLCV: existing A007 finite/positive-price/nonnegative-volume/OHLC checks fail.

Reasons may combine. Complete zero-volume rows remain observations, without any
claim of fillability. Source opens count for chronology even on excluded rows.
Excluded rows and absent rows are separate counts. Raw source must be retained
by the caller; the index itself does not copy or alter it.

HistoryIndex contains complete Candle objects with native timestamps, CompleteSpan
descriptors, excluded rows and missing intervals. All-excluded sources and singletons
are explicit. This unsigned local structure is not an authenticated trust object;
callers must not treat arbitrary constructed indexes as verified provenance.

index.complete_window(first_open_ms, end_exclusive_ms) checks aligned elapsed-time
coverage. A missing/excluded time or out-of-coverage bound returns false. It does
not approve a model feature/label. complete_history_window(indexes, first, end)
checks 1..256 ordered indexes, validating ALL symbols/intervals/source order before
returning success. Overlapping/reversed sources reject. Adjacent complete spans
may continue across file boundaries, but no real gap is bridged.

index.contiguous_dataset(span_index) explicitly exports ONE span through the
existing CandleDataset validator; singletons cannot be exported. Its hash identifies
the entire original source bytes, not separately serialized span bytes. No full-
source replay or position/cash management across missing prices is implemented.

## Coverage limitations

A file cannot establish requested calendar coverage at its edges. Callers must
check requested file/month boundaries and inventory separately. The index reports
first/last supplied source opens, not an inferred listing or calendar boundary.
Source labels/hashes do not independently verify price truth or instrument identity.

Learning must check the full elapsed-time window covering BOTH feature lookback
and forward target, not merely endpoint presence. Log excluded candidate-window
counts/reasons. Removing unavailable windows may underrepresent outage/stress
conditions; do not claim performance during those outages. This API is a coverage
check, not global enforcement against other code. Stock calendars, corporate
actions and derivatives rules remain separate adapter work.

## Real-data smoke fixture

examples/a011/BTCUSDT-1h-2021-02-excerpt.csv contains five exact rows 242..246
from the captured full CSV. It is a DERIVED EXCERPT, not the provider's full file.
SOURCE.json records archive/source/excerpt hashes, URLs, exact row selection and
matching provider checksum. The partial row is excerpt row 3. The excerpt has
four complete rows, one partial row, one missing hour and two two-row spans.
It is an intake smoke fixture, not a performance sample.

```bash
mkdir -p work
PYTHONPATH=app python -m ariyan_trading.historical_segments \
  --csv examples/a011/BTCUSDT-1h-2021-02-excerpt.csv \
  --symbol BTCUSDT --source 'Derived real excerpt; intake smoke only' \
  --interval-ms 3600000 --as-of-ms 1614556800000 \
  --output work/a011-history-smoke.json
```

Output creation is exclusive. A process interruption can leave a partial new
report; no authenticated/crash-safe publication guarantee is made.

## Checks and continuation

```bash
PYTHONPATH=app python -m unittest discover -s tests -p '*a011.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

20 tests cover hashes, declared exclusions/missing time, valid zero volume,
structural failures, bounds/units/future slots, singletons/all-excluded sources,
span export, elapsed-time/multi-file coverage, CLI no-overwrite/determinism and
the derived real fixture. Original strict intake still rejects the same input.
Local regression: 938 tests OK, one known expected failure. The saved local source
lacks A008; the target A010 checkout should discover 949 tests if otherwise
unchanged. A006's expected failure remains unresolved; no live-readiness claim.

R003 model comparison has NOT run. The intended small budget remains two fixed
models: expanded-history one-feature daily ridge and a standardized ridge using
24h/72h/168h returns plus 24h realized volatility. Record the exact executable
model protocol before performance, keep the June calibration / July–September
assessment / reserved exclusion, and first inventory/index the older source
archives. Enforce full contiguous feature-plus-target windows. Do not silently
shorten history, weaken strict replay intake or concatenate observations across
gaps merely to force a model run.
