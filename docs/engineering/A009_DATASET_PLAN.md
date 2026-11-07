# A009 — offline dataset plan and reservation

Target installation checkpoint: b0d8328 (A008). This adds dataset_plan.py and
its tests; A007, A008, ledger, authorization, default demo and CI are untouched.
No network, replay or order submission occurs.

## Contract

build_dataset_plan(dataset, development_candles=..., config=...,
stress_fee_bps="20", stress_slippage_bps="10", prior_data_access="unknown")
records the exact full-input byte hash, intake metadata, baseline/stress SMA test
settings, and two contiguous disjoint ranges covering every bar: DEVELOPMENT
followed by RESERVED. Each range needs long_window + 1 bars for mechanical replay
eligibility, with separate cold-start warmup and no carried positions. This is
not a statistical minimum. The plan computes no performance and grants no
passing grade, predictability or capital authority.

A007 validates the entire input including reserved rows. It rejects chronology
gaps, duplicates, misalignment, bad OHLC and incomplete bars. This feature neither
repairs data nor downloads, joins or authenticates sources. Existing 32 MiB and
100,000-candle limits apply.

verify_dataset_plan(dataset, plan) rebuilds the supported contract and compares
all fields, including JSON types, against the current validated dataset. The CLI
reloads the CSV from bytes before verification. Byte-only changes such as newline
conversions invalidate a saved plan even when candle values match. Source and
symbol remain caller labels. The stored hash covers the whole input, not ranges.
The plan reader rejects duplicate keys, non-finite JSON constants and files over
64 KiB. Creation is exclusive and never overwrites an input or previous plan.

## Reservation is a record, not enforcement

The unsigned plan snapshots settings and a boundary. It has no authenticated
publication time, external trust anchor or tamper-proof immutability. Coordinated
edits/recreation can produce another internally consistent plan. Keep the original
with the experiment record; changing it after results is a different experiment.
A007/A008 can still be called directly over any data. No runtime access-control
or holdout-consumption gate is added.

prior_data_access is one of unknown, previously_inspected, or
caller_declares_not_inspected. Every option keeps out_of_sample_status equal to
NOT_ESTABLISHED_CALLER_ASSERTION_ONLY. An uninspected-data declaration cannot
prove historical nonaccess. Parsing data for integrity is disclosed; no reserved
performance is computed here. Already viewed data cannot be made unseen by a
new split or label.

## Existing real-data integration smoke

The 24-bar A007 example was already inspected. Its two 12-bar ranges are solely
an integration check, not an adequate evaluation sample or unseen holdout.
From the repository root (choose another output name if one already exists):

```bash
mkdir -p work
PYTHONPATH=app python -m ariyan_trading.dataset_plan \
  --csv examples/a007/BTCUSDT-1h-2024-01-01.csv \
  --format binance-spot --timestamp-unit ms \
  --symbol BTCUSDT --interval-ms 3600000 \
  --source 'A007 existing Binance fixture; already inspected; smoke only' \
  --as-of-ms 1704153600000 \
  create --development-candles 12 --prior-data-access previously_inspected \
  --output work/a009-smoke-plan.json

PYTHONPATH=app python -m ariyan_trading.dataset_plan \
  --csv examples/a007/BTCUSDT-1h-2024-01-01.csv \
  --format binance-spot --timestamp-unit ms \
  --symbol BTCUSDT --interval-ms 3600000 \
  --source 'A007 existing Binance fixture; already inspected; smoke only' \
  --as-of-ms 1704153600000 \
  verify --plan work/a009-smoke-plan.json
```

Metadata and cutoff must match exactly when verifying. Config options follow
create; dataset options precede the create/verify subcommand. A failed write
may leave a partial new file on disk; it is not accepted as a valid plan merely
because it exists. No crash-safe authenticated publication is claimed.

## Verification and remaining work

```bash
PYTHONPATH=app python -m unittest discover -s tests -p '*a009.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twelve tests cover complete range coverage and warmup, no replay, minimum/invalid
boundaries, frozen settings and cost validation, honest access declarations,
changed bytes/metadata, schema/type tampering, hostile Decimal context, bounded
strict JSON, CLI determinism/verification/no-overwrite/failure, and a real-fixture
smoke. Synthetic candles are labeled test fixtures and are not market evidence.

Local verification uses the saved 4605f51 source (A007 plus CI dependency fix),
with these A009 additions. A008 is not present in that saved archive. Run the
full suite on the target b0d8328 checkout to verify A008 and A009 together before
committing. A006's known expected failure remains unresolved.

Next work: acquire a bounded larger real-data snapshot with provider/URL and
transfer checksums, record exact byte provenance and units, choose the experiment
settings/boundary before viewing performance, then connect planned ranges to
controlled evaluation. No larger dataset has been acquired by this milestone.
A future genuinely unobserved evaluation needs a defensible reservation process;
this local unsigned record alone does not establish one.
