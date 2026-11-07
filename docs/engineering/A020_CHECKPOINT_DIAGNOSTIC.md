# A020 — read-only checkpoint boundary diagnostic

Based on checkpoint `6b8aa53`. Three additive files; no changes to ledger,
enrollment, checkpoint publication, authorization, or existing tests.

## Purpose

The known A006 expected failure demonstrates a real boundary limitation:
publishing an external checkpoint does not mark the corresponding database as
managed. An ordinary legacy reopen can still accept direct paper ledger writes.
The checkpoint contains sequence/digest and an HMAC, but no managed enrollment
operation. A020 does not repair that limitation or remove the expected failure.

`inspect_checkpoint(database, opening_cash, checkpoint, key)` opens the existing
DurableLedger checkpoint facade with SQLite `mode=ro`. It then verifies metadata,
balances and checkpoint together in a read transaction, checking that the journal
tip has not advanced since the facade's initial verification. It always rolls
back its owned read transaction and closes the connection, including on failure.
Decimal arithmetic uses a fresh fixed precision context.

Inputs must already exist as regular files, without symlink components. Database
and checkpoint cannot be hardlink aliases. The supplied key must be raw bytes,
32..4096 bytes long. No anchor discovery, enrollment, repair, trading, network,
secret generation, or write attempt occurs during inspection.

## Interpretation

| Local mode metadata | Diagnostic boundary |
| --- | --- |
| Absent | `LEGACY_DIRECT_WRITE_BOUNDARY_NOT_ESTABLISHED` |
| `managed-v1` | `LOCAL_MANAGED_MARKER_PRESENT` |
| Any other value, including empty | `UNKNOWN_MODE_DIRECT_WRITES_FAIL_CLOSED` |

These describe the ordinary DurableLedger API guard. They are observations,
not authenticated writer enrollment or approval of a coordinator. A marker can
change without changing the anchored journal. The UUID is only a local identity
label and is not independently authenticated by the old checkpoint format.

A matching checkpoint establishes journal agreement with the supplied key only.
It does not establish the key's authority, secure custody, independent rollback
resistance, or continuing validity. A consistently restored older ledger and
checkpoint can still pass. All authority and independent-trust claims remain
false in every successful report, regardless of mode.

Pending publication, missing/stale/divergent anchors, invalid schema, bad balance
replay and wrong opening cash/key are rejected using existing verification rules.
Pending state is never cleared or bypassed. A successful report's
`publication_pending: false` means no pending marker was present in its snapshot.
An actual publication failure may therefore prevent diagnosis until a separately
designed recovery procedure establishes a valid checkpoint; A020 is not recovery.

## Command

The command prints JSON to standard output. It does not create an output file.
Use explicit existing paths for a ledger you are authorized to inspect:

```sh
PYTHONPATH=app python -m ariyan_trading.checkpoint_diagnostic \
  --database /explicit/path/ledger.sqlite \
  --opening-cash 1000.00 \
  --checkpoint /explicit/path/checkpoint.json \
  --checkpoint-key-file /explicit/private/path/checkpoint-key.bin
```

The key file is raw binary, not hex text; no stripping or conversion occurs.
Do not create a replacement key for an existing ledger. The command rejects key
files aliased to either input, bounds the read and does not echo private input
exceptions. Keep key files private and outside source control. The report includes
the journal tip, UUID label and local mode; it contains no key or key digest.

Exit 0 means inspection completed, including a legacy-boundary warning. It never
means permission to write or trade. Exit 2 means inspection rejected; no successful
JSON report is emitted. SQLite read-only access can use SQLite-managed WAL/SHM
sidecars; this is not an assertion of zero filesystem activity or immutable media.
No initialization lock or database schema initialization is requested.

## Validation

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a020.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Eighteen tests cover modes and marker mutation, the existing legacy reopen
limitation, managed blocking, pending publication, stale/missing/corrupt anchors,
wrong cash/key and key bounds, symlinks/aliases, read-only SQL enforcement,
unchanged default-journal input bytes, handle cleanup on success/failure, isolated
Decimal context, deterministic fresh-process JSON, CLI rejection without key
echo and a journal advance between initial verification and inspection.

The original A006 expected failure remains. Authenticated enrollment and write
admission require a separate reviewed design; this diagnostic grants no authority.
