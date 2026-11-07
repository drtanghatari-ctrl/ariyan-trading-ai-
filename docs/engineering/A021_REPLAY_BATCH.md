# A021 — multi-instrument offline replay jobs

Based on `d592e93`. Adds `replay_batch.py`, its tests and this document. Existing
ledger, checkpoint, authorization, intake and replay implementations are unchanged.

## Behaviour

One manifest declares 1..8 named replay jobs. Each job supplies its own canonical
CSV, A012 instrument record, A014 session schedule, A015 intake declarations and
complete A017 configuration. Jobs run sequentially in manifest order. Every job
starts with its own opening cash, zero holdings, empty signals and fresh risk
state. Holdings still carry across session closures *within* a job as in A017.

The result is one JSON file containing all full replay reports and a summary
table. Each row retains venue-qualified identity, currency, opening cash, marked
equity/PnL, return, fees, modeled slippage, fills, drawdown, halt state, terminal
units and mark time/staleness. Display symbols do not determine identity.

| Boundary | Contract |
| --- | --- |
| Accounts | Independent resets; no shared cash, positions or risk budget. |
| Currencies | Explicit per job; no FX conversion or aggregate PnL/return. |
| Repeated instruments | Allowed with distinct job IDs; no independent-evidence claim. |
| Parameters | All A017 configuration fields required; no implicit parameter defaults or search. |
| Failures | Any job failure rejects the batch; no partial successful-job report is published. |
| Inputs | All references parsed before replay; hashes rechecked before output creation. |
| Output | One exclusively created file; never replaces an input or prior report. |
| Authority | No ledger posting, strategy promotion, account connection or live authority. |

## Scope

The same existing cash replay can consume declared crypto spot, equity shares,
fund shares and positive-price metal/energy spot terms. This is a workflow over
caller declarations, not a newly authenticated market adapter. Gold, silver or
oil labels alone do not identify a tradable product. Futures, CFDs, leverage,
shorting, currency conversion and derivatives accounting remain unsupported.

Actual stock/commodity feeds, exchange calendars, corporate actions, dividends,
delivery/storage, expiry/roll and venue execution still require separate work.
Do not treat fund shares or spot declarations as substitutes for futures/CFDs.
Synthetic tests exercise the shared mechanics only. The real BTC test uses 24
previously retained candles and unverified synthetic terms/calendar: smoke only.

All A017 completeness, session warmup, timing, fillability, risk-exit and terminal
valuation limitations remain in each nested report. A missing-session bar or
unknown/off-session observation still rejects replay; no interpolation occurs.
Drawdown halts cannot guarantee maximum losses or liquidation.

## Explicit manifest

Save UTF-8 JSON with exact fields. Relative file references resolve against the
manifest's directory, independent of the process working directory. Absolute
paths are also accepted. Inputs must exist as regular files without symlink
components; output's parent must already exist. No files are downloaded.

The following is a schema template for one job. It requires existing, separately
prepared instrument/schedule/CSV files whose terms and coverage actually match:

```json
{
  "version": "ARIYAN-A021-REPLAY-BATCH-REQUEST-V1",
  "jobs": [
    {
      "job_id": "btc-development-base",
      "csv": "btc/candles.csv",
      "instrument": "btc/instrument.json",
      "schedule": "btc/schedule.json",
      "intake": {
        "symbol": "BTCUSDT",
        "source": "CALLER MUST SUPPLY ACTUAL SOURCE LABEL",
        "mapping_source": "CALLER MUST SUPPLY EXPLICIT MAPPING EVIDENCE LABEL",
        "volume_unit": "BTC",
        "price_basis": "RAW_UNADJUSTED_SINGLE_INSTRUMENT",
        "interval_ms": 3600000,
        "anchor_ms": 0,
        "first_open_ms": 1704067200000,
        "end_exclusive_ms": 1704153600000,
        "as_of_ms": 1704153600000
      },
      "config": {
        "opening_cash": "1000",
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

Append other explicit job objects for other instruments or predeclared cost
scenarios. IDs must be unique, 1..64 characters, using letters/digits, dot,
underscore or hyphen, beginning with a letter/digit. Decimal configuration values
must be JSON strings; windows/limits and millisecond values must be exact JSON
integers. Unknown/missing keys, duplicate JSON keys, NaN/Infinity and type confusion
are rejected. There is no automatic baseline/stress expansion or ranking.

```sh
PYTHONPATH=app python -m ariyan_trading.replay_batch \
  --manifest work/explicit-jobs.json --output work/batch-results.json
```

Exit 0 means the declared offline batch completed, even if all results lose money,
halt or make no trades. It does not mean a strategy passed validation. Exit 2
means rejection. The command prints one concise result per job and report path.

## Bounds and provenance

Manifest: 256 KiB. At most 8 jobs, 40,000 grid slots across jobs, 10,000 per job
as already required by A017, and a 32 MiB combined report. Input accounting caps
referenced input bytes at 64 MiB, counting repeated references each time and
conservatively reserving the full manifest allowance. Existing per-file CSV,
instrument and schedule limits still apply. Source-file hashing has its existing
separate per-file bounds. These are resource limits, not scientific sample minima.

The report records manifest and per-job input byte hashes, the A018 source list
plus `replay_batch.py`, Python version, and an unsigned domain-separated batch
hash. It retains full nested limitations. Reproduction requires the same inputs,
configuration, source and Python environment. Source file hashes are not loaded
code attestation. Input rechecks do not create an atomic/authenticated snapshot,
prevent change-and-restore races, or establish calendar/data authenticity.

Validation failures before publication create no output. Ordinary write exceptions
remove the file created by that write; a competing file at exclusive creation is
preserved. No fsync, power-loss durability or invisibility of an in-progress write
is promised. Output is intended for an owned workspace, not hostile filesystem
mutation during publication.

The batch does not consume A009 reservations or establish out-of-sample status.
Callers must explicitly choose permitted development inputs. Existing original
reserved performance was not evaluated during A021 development. Selecting jobs
or comparing variants after seeing outcomes still creates selection bias. Jobs
sharing instruments/data are correlated, and capital/returns cannot be combined
into a funded portfolio. No optimization, scientific adequacy or profitability
claim is made.

## Checks

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a021.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-three tests cover standalone-engine agreement, cash/currency/risk isolation,
local halt latching, order preservation, identity collisions, repeated instruments,
synthetic cross-asset terms, real BTC base/stress smoke, strict schemas/types,
incomplete data and unsupported futures/FX, bounds, path protection, deterministic
fresh-process reports/hashes, input/source changes, exclusive-create races, write
cleanup, context isolation, authority flags and CLI errors. No `os.link` fixture
or platform hardlink API is needed. A006's known expected failure remains.
