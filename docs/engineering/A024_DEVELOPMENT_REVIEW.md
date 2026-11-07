# A024 — verified development review workflow

Based on `44342f5`. Adds `development_review.py`, tests and this document. Existing
export, engine, batch, viewer, ledger and authorization modules are unchanged.

## Workflow

`run_development_review(request_path, destination)` connects the existing pieces:

1. Strictly read an explicit request with an experiment note and 1..8 named jobs.
2. Verify **every** A023 export against its original full CSV and A009 plan before
   any replay. Select each job's declared `base` or `stress` plan configuration.
3. Require all shared A009/A017 settings to match: opening cash, fee/slippage,
   buy/exposure fractions and short/long windows. Decimal spellings may differ
   numerically; JSON types must still satisfy A021's exact contract.
4. Copy only verified development CSVs, export receipts/plans and explicit
   instrument/session JSON into a new owned directory. Original full CSVs are
   hashed/rechecked but never copied into the review directory.
5. Derive intake metadata and exact development timestamps from the verified
   export; write a relative-path A021 manifest, then run A021 and render A022.
6. Recheck original/request/metadata inputs, implementation files and every copied
   or produced artifact. Write `COMPLETE.json` last, with artifact byte hashes and
   separate per-job summary rows.

The HTML displays the caller's escaped experiment note and development-only scope
above the existing A022 review. The original full source, including reserved rows,
is parsed for integrity only. Each engine receives only its verified development
slice. Cash, positions, signals and risk state reset independently per job.

## Request

Paths resolve against the request file's directory. Inputs must exist without
symlink components. The export directory must already have passed A023 export;
the instrument and schedule are explicit caller files, not invented by A024.
The output parent must already exist and its destination must be new.

```json
{
  "version": "ARIYAN-A024-DEVELOPMENT-REVIEW-REQUEST-V1",
  "experiment_note": "Document the execution-model/risk revision and prior data access; no validation claim.",
  "jobs": [
    {
      "job_id": "declared-instrument-base",
      "original_csv": "snapshot/candles.csv",
      "plan": "plans/dataset.plan.json",
      "export_directory": "development-export",
      "instrument": "metadata/instrument.json",
      "schedule": "metadata/schedule.json",
      "scenario": "base",
      "mapping_source": "CALLER MUST SUPPLY AN EXPLICIT MAPPING LABEL",
      "volume_unit": "BTC",
      "price_basis": "RAW_UNADJUSTED_SINGLE_INSTRUMENT",
      "config": {
        "opening_cash": "10000.00",
        "cash_currency": "USDT",
        "cash_step": "0.01",
        "fee_bps": "10",
        "slippage_bps": "5",
        "price_convention": "QUOTE_CURRENCY_PER_ONE_QUANTITY_UNIT",
        "max_buy_fraction": "0.10",
        "max_position_fraction": "0.25",
        "max_close_drawdown_pct": "10",
        "short_window": 3,
        "long_window": 5,
        "max_trades": 1000
      }
    }
  ]
}
```

This is a schema template, not a ready-to-run market profile. Its shared values
must match the supplied plan/scenario and currency/units must match the actual
declared instrument. All A017 configuration fields are explicit. Cash step,
currency, price convention, drawdown halt and fill-record limit are additional
settings absent from A009; A024 records them without asserting A007 execution
equivalence. The experiment note is an unsigned caller statement, not proof that
choices preceded data inspection. No automatic parameter tuning or cost-scenario
expansion occurs. For stress, supply another named job with `scenario: "stress"`
and the saved plan's stress shared values.

A009's original loader requires continuous epoch-aligned candles. Therefore the
derived anchor is zero and the full development range is used. This bridge does
not add session-gap plans for stock calendars. A021 remains separately available
for explicitly prepared session-series jobs. A024 adds no venue adapter, corporate
action processing, futures/CFD/margin accounting or live execution.

```sh
PYTHONPATH=app python -m ariyan_trading.development_review \
  --request work/development-review-request.json \
  --destination work/development-review-v1
```

## Outputs

| File/path | Purpose |
| --- | --- |
| `REVIEW_REQUEST.json` | Exact request bytes for audit; relative originals still refer to the recorded request-origin directory. |
| `PLAN_BINDINGS.json` | Experiment note, plan/export/input hashes, development/reserved bounds, scenario/settings relationship and limitations. |
| `inputs/job-NN/export/` | Exactly the three copied A023 files; no original full CSV. |
| `inputs/job-NN/instrument.json`, `schedule.json` | Exact caller declaration bytes. |
| `batch-request.json` | Relative-path A021 request pointing to copied development inputs. |
| `BATCH.json` | Full A021 report; no shared portfolio or currency aggregation. |
| `REVIEW.html` | Offline A022-derived page with visible experiment context. |
| `COMPLETE.json` | Written-last completion record, artifact hashes and summary rows. |

The relative batch manifest remains usable with its copied inputs if the review
directory is moved. `REVIEW_REQUEST.json` is an audit copy, not an automatically
relocatable request for the original inputs. Open `REVIEW.html` locally. HTML uses
no scripts or remote assets. The A022 browser-layout limitation remains: no actual
browser visual check was available in this build environment.

## Limits, failures and interpretation

A024 caps referenced input payloads at 64 MiB, the completion record at 256 KiB,
and the complete bundle at 128 MiB. Repeated references count each time; source
fingerprinting and verification rereads are additional IO, not a wall-time/memory
guarantee. Existing per-file and per-engine limits remain: 8 jobs, 40,000 grid
slots across an A021 batch, 10,000 per job, 32 MiB batch JSON and 16 MiB contextual
HTML. A mechanically valid request can still exceed a report or fill-record cap.

Any validation/recheck/engine/view failure rejects completion. Ordinary failures
remove only still-owned paths; replaced or unrelated concurrent files are
preserved. No existing or racing directory is adopted. Unexpected files block
completion. This is not atomic publication or power-loss durability: a running
or interrupted directory can be observed, and `COMPLETE.json` presence alone is
not authenticated evidence. Artifacts/hashes are unsigned and can be recreated.
There is no hostile-filesystem or change-and-restore-race guarantee.

Successful completion means this fixed offline workflow finished, not that any
strategy passed. The original full inputs and other APIs remain accessible. The
workflow is an operation-specific boundary, not global holdout access control,
authenticated experiment publication, a holdout-consumption ledger, established
out-of-sample validation, profitability or capital authority. Declared instrument,
calendar and cost terms remain unverified. A017 fillability, risk-exit, warmup,
session, stale-mark and terminal-inventory limitations all remain. Matching shared
SMA/settings does not make A017 tick/cash rounding and drawdown exits equivalent
to A007/A008. The test strategy remains unvalidated.

## Checks and local integration

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a024.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-two tests cover end-to-end standalone-engine agreement, copied hashes and
HTML, development-only engine inputs, scenario/shared-setting checks, explicit
extra risk settings, escaped experiment notes, all-export preflight, changed
originals/exports, exact schemas/types, invalid metadata, no-overwrite/symlinks,
input/source/staged/report mutation, viewer/completion failures, foreign-file
preservation, directory races, bounds, Decimal isolation, deterministic CLI runs,
no authority and the retained 12-bar real BTC development smoke. No `os.link`
fixture is required. The known A006 expected failure remains unresolved.

The retained BTCUSDT, ETHUSDT and SOLUSDT Jan–Sep 2024 development data were also
checked with one fixed 3/5 SMA implementation, saved base/stress shared settings,
cent cash, eight-place research price/quantity grids, one continuous declared
window, a 10% observed-close drawdown halt and 1,000-fill limit. These are explicit
research assumptions, not verified historical venue filters or a new validated
strategy. No reserved performance was evaluated.

The original six-job batch exceeded the existing 32 MiB report cap and was rejected
without completion. The identical jobs/ranges/settings were partitioned solely
for resources into three per-instrument base/stress reviews. No cost, strategy,
data boundary or risk setting was selected based on outcomes. Every scenario lost
money and latched its simulated halt:

| Instrument | Base return | Stress return | Base/stress fills |
| --- | ---: | ---: | ---: |
| BTCUSDT | -8.7862% | -8.8271% | 404 / 236 |
| ETHUSDT | -9.4245% | -9.4316% | 840 / 307 |
| SOLUSDT | -8.2739% | -8.2667% | 556 / 232 |

Returns are from separate 10,000-USDT simulated accounts and are not additive.
The halt uses drawdown from an observed peak, not loss from starting cash, and
does not guarantee an exit price or maximum loss. Higher costs can alter trade
paths and halt timing. These implementation checks on previously inspected data
do not establish profitability or independent validation. A presentation-only
context addition reproduced the same batch bytes; it is not independent evidence.
