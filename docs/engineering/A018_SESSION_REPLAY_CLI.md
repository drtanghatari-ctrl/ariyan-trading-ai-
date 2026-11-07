# A018 — explicit-file offline session replay command

Based on A017 checkpoint `99edd62`. Adds `session_replay_cli.py`, twenty tests
and this document. Existing intake, replay, cash arithmetic, ledger, authorization,
default demo and CI code are unchanged. No network/account operation or new
real-market research assessment is added.

## Command contract

`PYTHONPATH=app python -m ariyan_trading.session_replay_cli` provides a file-based
entry point for A015 intake and A017 replay. It requires three explicit inputs:
canonical candle CSV, A012 instrument JSON and A014 schedule JSON. The caller
also supplies symbol/source/mapping labels, price/volume conventions, grid/time
bounds, opening cash, currency/precision, fees and slippage. There is no inferred
production instrument, exchange holiday table or silently assumed zero cost.

Instrument JSON uses `InstrumentSpec.to_record()` and must satisfy the exact
A012 schema through `spec_from_record()`. Schedule JSON uses
`SessionSchedule.to_record()` and the exact A014 schema through
`schedule_from_record()`. Decimal instrument terms must be strings, enum values
must be supported strings, and unverified/enforcement flags must remain false.
Duplicate JSON keys, nonfinite constants, non-object roots and unsupported fields
or claims are rejected. Numeric/order/currency/calendar rules remain those of
A015–A017; this command does not weaken them to produce a report.

Metadata limits are 64 KiB for instrument JSON and 16 MiB for schedule JSON,
in addition to A014's 10,000-window bound. A015 CSV remains limited to 32 MiB
and 100,000 rows. A017 replay still limits total grid slots to 10,000 and trades
to the configured maximum, at most 1,000. Output is bounded to 32 MiB.

## Explicit usage

The following is a command template using caller-established files/values;
these are not installed real venue specifications. Parent output directories
must already exist.

```
PYTHONPATH=app python -m ariyan_trading.session_replay_cli \
  --csv work/candles.csv \
  --instrument work/instrument.json --schedule work/schedule.json \
  --symbol DECLARED_SYMBOL --source 'Caller source record' \
  --mapping-source 'Caller mapping; independent verification pending' \
  --price-basis RAW_UNADJUSTED_SINGLE_INSTRUMENT \
  --volume-unit DECLARED_QUANTITY_UNIT \
  --interval-ms 3600000 --anchor-ms 0 \
  --first-open-ms FIRST_OPEN --end-exclusive-ms END --as-of-ms AS_OF \
  --opening-cash 10000 --cash-currency DECLARED_CURRENCY --cash-step 0.01 \
  --fee-bps 10 --slippage-bps 5 \
  --price-convention QUOTE_CURRENCY_PER_ONE_QUANTITY_UNIT \
  --output work/a018-report.json
```

Replace all placeholders and cash precision/costs with the explicitly declared
model. This is not a suggested real fee schedule, currency policy, trading
instrument or assessed parameter set. All arguments above are required.
Optional A017 defaults remain visible in the resulting config: short/long SMA
windows 3/5, per-buy fraction 0.10, position fraction 0.25, observed-close drawdown
halt 10%, and 1,000 trade-record limit. They are test settings, not risk approval.
Use `--help` for their flags; no new strategy/search path exists.

The command prints observed candle and simulated fill counts, halt state and
report path. It deliberately states offline/no promotion. Full descriptive
marked returns, holdings, decisions, fees and failed execution attempts remain
inside the unchanged A017 report; nothing is graded as a validated edge.

## Output and provenance

The wrapper records:

* exact raw byte hashes of the canonical CSV snapshot consumed by A015 and of
  both metadata JSON files consumed here;
* the entire A017 replay with its A015 intake, specifications, schedule, grid,
  canonical candle hash, costs, limits and limitations;
* SHA-256 of ten named implementation source files and the current Python version;
* false source-authentication, strategy-promotion and live-authority flags.

`run_sha256` hashes every other wrapper field using compact sorted ASCII JSON
and the `ARIYAN-A018-SESSION-REPLAY-RUN-V1` domain plus NUL. The stored JSON is
sorted, indented ASCII with a final newline. Output paths/input filenames are
not embedded, so repeated runs under the same sources/Python/runtime inputs can
produce identical report bytes at different destinations. Different Python
versions or file formatting may change provenance bytes even when scientific
values agree. No cross-environment identity is promised beyond tested arithmetic.

Original provider archives, signatures and public timestamps are not loaded
or authenticated here. A derived canonical CSV hash identifies that derived
file, not a provider ZIP. Raw metadata hashes preserve file spelling/format;
A012/A014 fingerprints separately identify their canonical values. Neither
hash layer proves venue truth, freshness, information availability or authority.

Implementation hashes describe the source-tree files read during the run, not
an authenticated loaded-bytecode/runtime attestation or complete software bill
of materials. This command expects the regular source checkout with the named
`.py` files present, each bounded to 256 KiB; zip-only/bytecode-only installations
are not supported by the provenance recorder. Python/OS/library trust is not
established by these hashes.

## No overwrite and failure behaviour

All file paths must be normalized regular paths; symlink file/parent paths are
rejected. The output must not already exist and its parent must exist. An input
cannot be used as the output. All parsing, intake, replay, encoding and size
checks complete before exclusive report creation. The command rechecks input
and named source-file bytes before publication and refuses changed files.

The reads/rechecks are best-effort ordinary consistency checks, not one atomic
multi-file snapshot, a filesystem lock or a concurrent-adversary guarantee.
There is no independent capture-time anchor. The in-memory replay consumes the
captured objects; future file changes do not retroactively authenticate them.

Expected rejection exits with status 2 and creates no report. If exclusive
creation loses a race to another writer, that writer's file is preserved. A
caught write/close failure removes only this command's owned partial report.
No parent directories are created. No fsync/crash-safe publication guarantee is
made; a killed process can leave a partial file that must not be treated as a
verified successful run. Existing reports are never overwritten or auto-deleted.

## Integration evidence and remaining boundary

Tests execute the actual module in fresh Python processes, compare with the
direct A017 API, verify repeatable report bytes and reconcile input hashes.
One smoke test converts the existing real 24-bar BTC fixture into canonical
CSV and runs the same command. Its instrument terms and full-day schedule are
explicitly synthetic/unverified declarations. No current/historical Binance
filter, authoritative trading calendar or actual fill specification is supplied.
The test asserts mechanics/hashes, not a return threshold or sample adequacy.

This is a practical entry point, not venue/calendar verification or a production
adapter. A017's strict-completeness conditioning, session resets, unliquidated
marks, simulated execution, incomplete corporate-action handling and drawdown
limitations all remain. Nested older-component flags retain their original
contracts; the command does not upgrade them. No new model is fitted, no R001–R004
outcome is selected/recomputed, and original reserved performance is not evaluated.

Actual verified source/calendar/contract inputs, prospective validation, wider
execution realism and authenticated capital authority remain separate work.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a018.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty tests cover real command/direct-API equivalence, fresh-process determinism,
raw/run hashes, real-fixture smoke, explicit conventions, malformed metadata/data,
reference/configuration rejection, byte bounds, existing-input/report protection,
missing parents, symlinks, changed inputs/sources, failed-write cleanup and
output-creation races. The known A006 expected failure remains unresolved.
