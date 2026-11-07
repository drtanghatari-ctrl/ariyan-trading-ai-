# A025 — read-only saved review inspection

Based on `10fb554`. Adds `review_inspector.py`, its tests and this document. It
does not modify A024, any replay engine, the viewer, ledger or authorization code.

## Purpose

A024 writes a completed development review but its presence alone does not make
it intact or authentic. A025 checks a saved directory after copying or reopening
it. `inspect_review(directory)` returns a consistency result. It creates no output
files, repairs nothing, reruns no strategy and opens no original full CSV/plan.
The original inputs may be absent, and a complete review folder may be moved.

The exact supported folder contains the six A024 root files and five copied input
files per job in their expected `inputs/job-NN/` layout. Missing/extra entries,
nonregular artifacts, symlinks, unsafe hash-map keys and manifest paths that could
refer outside those copied inputs are rejected before the manifest is consumed.
Recorded original paths in `REVIEW_REQUEST.json` are labels only and are never
followed by this inspector.

## Checks

| Area | Check |
| --- | --- |
| Completion | Supported exact schema, 1..8 jobs, false authority flags and artifact hash map matching the expected tree. |
| Bytes | Every listed artifact's SHA-256, with per-file and aggregate bounds; final byte/tree rechecks detect ordinary changes during inspection. |
| Request and bindings | Request digest, experiment note, IDs, scenarios, shared settings, development/reserved metadata and copied plan/export references agree. |
| Copied export | Supported plan/export versions, unsigned export digest, plan byte hash, normalized CSV hash and recorded development-only claims agree. |
| Batch report | Existing A022 displayed-field consistency checks, unsigned batch digest, repeated summaries and recorded producer hashes agree. |
| Copied intake | Rebuild A015 intake from the copied CSV/spec/schedule without invoking A017; compare full intake and input hashes with the saved batch. |
| HTML | Recreate the supported A022 page plus A024 experiment context and compare every byte with `REVIEW.html`. |

The inspector checks development row count, its zero-based index span, the
reserved start boundary, range end and normalized CSV spelling against copied
series metadata. It does not rebuild or independently authenticate the full A009
plan contract against the missing original full dataset. Comparing copied plan
fields and receipts is not proof that their original claims were truthful.

## Use

```sh
PYTHONPATH=app python -m ariyan_trading.review_inspector \
  --review work/development-review-v1
```

The command prints JSON only. Exit 0 means the supported copied artifacts passed
these consistency checks. Exit 2 means rejection. There is no report creation,
account access, network, data acquisition, model fitting, replay, ledger posting,
enrollment, approval or trade. No reserved performance is newly evaluated.

The successful status is deliberately:

```
CONSISTENT_SAVED_ARTIFACTS_NOT_AUTHENTICATED
```

Successful output keeps `original_full_inputs_reopened`,
`original_full_inputs_independently_verified`, `replay_rerun`,
`source_authenticity_established` and `live_authorized` false. It does not promote
a strategy or add a passing investment grade. Even consistently losing reports
can pass file inspection.

## Limits and trust boundary

Existing A021/A022/A024 bounds apply: up to 8 jobs, 32 MiB batch JSON, 16 MiB HTML,
32 MiB CSV per file, 16 MiB schedule, 64 KiB instrument/plan, 256 KiB completion,
request/binding/receipt metadata limits as declared by their writers, and 128 MiB
total artifact bytes. Directory enumeration is capped at 128 nodes. Copied intake
reconstruction retains the existing batch input and grid-slot bounds. These are
resource guards, not sample-size or scientific-adequacy requirements.

**All records and hashes are unsigned.** A caller can edit and consistently
recreate them. The original full input, reserved candle values, publication time,
key custody, prior data access, source truth and independent rollback resistance
are not established. Recorded producer hash maps are compared as claims; they do
not attest the code actually loaded or independently authenticate the producer.
No verification result becomes writer admission or capital authority.

The inspector does not rerun signals, fills, venue rules or the original strategy.
Rebuilt intake/summary/HTML agreement is copied-artifact consistency, not an
independent economic replication. A007/A017 execution differences, historical
data exposure and all existing market/risk limitations remain.

HTML comparison expects the current supported A022/A024 rendering semantics.
Legitimate future renderer changes may require a separately reviewed versioned
inspector; an old page is not silently rewritten. File/tree rechecks do not form
an atomic or authenticated snapshot and cannot exclude hostile filesystem or
change-and-restore races. A rejection never deletes or repairs the saved folder.

## Validation

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a025.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Nineteen tests cover intact/moved reviews with original inputs removed, no writes
or replay, missing/partial completion, altered artifacts, unsafe paths/maps,
symlinks/nonregular/unknown entries, rehashed summary/binding/CSV/HTML mismatches,
authority/schema/type rejection, JSON/node/byte bounds, changes during inspection,
consistent recreation without authentication, Decimal isolation, deterministic
CLI results and preventing a changed manifest from redirecting intake to originals.
Copied intake uses already checked request fields and fixed local paths, rather
than reopening file references from a mutable manifest. No hardlink API is required.

The three retained A024 BTCUSDT/ETHUSDT/SOLUSDT base/stress review folders also
passed this inspection locally, two jobs each. No replay was rerun. Their six
negative scenarios remain negative; this milestone provides no strategy promotion
or new profitability evidence. The known A006 expected failure remains unresolved.
