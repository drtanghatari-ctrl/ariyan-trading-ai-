# A023 — verified-plan development export

Based on `3bdd4f9`. Adds a module, tests and this document. Existing plan, replay,
batch, viewer, ledger and authorization modules are unchanged.

## Purpose and contract

A009 records a development/reserved boundary but does not enforce a global access
policy. A021 can consume any explicitly supplied CSV. A023 provides a bridge:
verify the original full input against its original A009 plan, select exactly that
plan's DEVELOPMENT range, and write a separate canonical CSV containing only those
candles. It computes no strategy performance and does not run an engine.

`export_development(csv_path, plan_path, destination)`:

1. Requires existing regular full CSV and plan inputs with no symlink components.
2. Loads the full source using the plan's symbol, source, format, timestamp unit,
   interval and explicit cutoff, and calls existing `verify_dataset_plan`.
3. Selects the verified development slice, preserving its chronology and values.
   There is no custom boundary, timestamp repair or reserved-range export option.
4. Creates one new directory exclusively, then writes three files with exclusive
   creation. `EXPORT.json` is written last after another input/source recheck.

| Output | Meaning |
| --- | --- |
| `development.csv` | Exactly the planned development candles, canonical six-column CSV, timestamps in ms, LF endings and normalized fixed decimal spelling. |
| `dataset-plan.json` | Byte-for-byte copy of the original verified plan, including reserved boundary metadata but no reserved candle values. |
| `EXPORT.json` | Original/full-input and new/subset hashes, plan byte hash, ranges, preserved configurations/access declaration, implementation file hashes and explicit limitations. |

The subset's hash identifies its actual normalized bytes. It is never assigned
the parent source's hash. Numeric normalization preserves candle values rather
than their original string spelling; Binance microseconds become exact ms using
the original strict loader. Export length and first/last timestamps follow the
verified range. Cold-start warmup bars remain inside that range.

The receipt's `reserved_candles_exported` is zero, and its performance-evaluated
flags describe this operation only. No historical claim that other users/tools
have never evaluated or inspected reserved data is made. The full source,
including reserved rows, is parsed and rechecked for integrity, as in A009.

## Verification

`verify_development_export(csv_path, plan_path, destination)` requires the original
full CSV and plan. It rebuilds expected output from those inputs and compares all
three files byte-for-byte, including the receipt. Changed/missing/extra files,
symlinks, source changes, modified plan/configuration, changed implementation
hashes, partial output and unrelated files in the export directory are rejected.
It does not trust a standalone receipt or its unsigned digest as original evidence.

Verification expects the same supported implementation source files, because their
hashes form part of the receipt. Later changes to those files can require an
explicit migration/re-export; they do not silently rewrite old evidence. The
recorded file hashes are not loaded-code attestation or signatures.

## Commands

Use explicit existing original paths and a new output directory. Its parent must
already exist; neither original input nor an earlier directory is overwritten:

```sh
PYTHONPATH=app python -m ariyan_trading.development_export export \
  --csv /explicit/snapshot/candles.csv \
  --plan /explicit/plans/dataset.plan.json \
  --destination work/development-export-v1

PYTHONPATH=app python -m ariyan_trading.development_export verify \
  --csv /explicit/snapshot/candles.csv \
  --plan /explicit/plans/dataset.plan.json \
  --destination work/development-export-v1
```

Exit 0 means export creation or comparison completed. Exit 2 means rejection.
No network, key creation, enrollment, trade, replay, model fit, optimization or
strategy selection occurs. Source and output input reads remain bounded: full
CSV and normalized subset 32 MiB each, plan 64 KiB, receipt 256 KiB, and existing
100,000-candle limit. Source hash reads retain A018's per-file bounds.

## Integration boundary

The exported CSV can serve as an explicit A021 job input alongside an independently
prepared instrument record, session schedule and complete A017 configuration.
Use the exported metadata's symbol/source/interval/cutoff and range timestamps
when preparing intake declarations. For byte provenance, record the exported CSV
hash and preserve the original/full source and copied plan as separate records.

A009's base/stress configuration is preserved exactly. A023 does **not** translate
A007 arithmetic into A017's cash grids, tick slippage, risk halt or session rules,
and does not invent historical venue terms. Those choices require an explicit
documented experiment revision. A future session-aware run is not automatically
an exact reproduction of the old A007/A008 evaluation.

The original full source, all other APIs and any caller-made copies remain
accessible. A023 is an operation-specific boundary, not a global reservation
runtime, holdout-consumption ledger or access-control mechanism. The plan/receipt
are unsigned, with no authenticated publication time or secure custody. A caller
can recreate a different consistent plan. Prior data access remains an unverified
declaration; already inspected data cannot become unseen. Out-of-sample status,
source truth, statistical adequacy, profitability and capital authority remain
unestablished. The original A009 `reservation_enforced_by_runtime: false` is retained.

## Failure and publication limits

Existing/racing directories are never adopted or replaced. On ordinary write or
recheck failure, cleanup removes only files whose recorded device/inode still
match and removes the directory only if empty and still owned. Replaced paths or
unrelated concurrent files are preserved. No `os.link` call is required.

There is no atomic directory publication, file fsync, transaction across files or
power-loss durability claim. An in-progress directory can be observed. Process
death can leave partial output; a receipt alone is not proof of completion. Always
run verification with the original inputs before relying on an export. These
checks do not protect against hostile filesystem mutation or change-and-restore
races, and do not create an atomic snapshot of inputs/source code.

## Checks

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a023.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-two tests cover exact development values/coverage, no reserved exports,
separate byte provenance, normalization, no replay/authority, changed original
bytes and invalid reserved OHLC, plan schema/config/boundary/type tampering,
recreated-plan limitations, full verification, no-overwrite/symlinks/aliases,
resource bounds, input/source changes, exclusive directory races, partial-write
cleanup with replacement/unrelated-file preservation, Decimal context isolation,
Binance us-to-ms conversion, deterministic fresh processes and CLI rejection.
The real BTC 24-candle fixture is smoke only: 12 development and 12 reserved bars.

Additional local integration checked the retained 2024 BTCUSDT, ETHUSDT and SOLUSDT
snapshots against their saved plans: 6,576 development candles each, zero reserved
candles exported, followed by full export verification. No performance was
computed. A006's known expected failure remains unresolved.
