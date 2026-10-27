# A006-WB02-P3C — Enrollment Safety Contract

Status: DESIGN ONLY — NOT IMPLEMENTED

## Scope

Define safe enrollment of an existing protected paper-trading
ledger into checkpoint-managed writer mode.

This document does not authorize real-money trading.

## Existing verified foundation

- Persistent canonical UUIDv4 ledger identity.
- Protected SHA-256 journal commitment chain.
- Authenticated checkpoint anchor.
- Authenticated writer-policy primitives.
- Read-only historical enrollment evidence verifier.
- SQLite transactional ledger.
- Existing direct-writer guard.

## Security invariants

P3C-01:
Enrollment requires an explicit operator-authorized action.

P3C-02:
Enrollment must begin from a verified authenticated checkpoint.

P3C-03:
Enrollment policy must bind the ledger UUID, enrollment
sequence, and historical journal digest.

P3C-04:
A committed enrollment-pending state must block ordinary
direct ledger writes.

P3C-05:
An interrupted enrollment must not be automatically
classified as successfully enrolled.

P3C-06:
An incomplete, invalid, or contradictory enrollment state
must fail closed.

P3C-07:
Policy publication must use atomic replacement and
appropriate filesystem synchronization.

P3C-08:
Concurrent writers must not bypass enrollment restrictions.

P3C-09:
Recovery must be explicit, auditable, and separately
authorized. Automatic re-enrollment is prohibited.

P3C-10:
Existing legacy behavior must not be changed until
enforcement and compatibility tests are complete.

P3C-11:
Database-local markers and policy files do not independently
prevent coordinated rollback or deletion.

P3C-12:
An independently protected trust record is required before
claiming downgrade resistance against coordinated rollback.

P3C-13:
No broker connectivity, capital authorization, or live
execution is introduced by enrollment.

## Proposed states

LEGACY:
No established managed-enrollment evidence.
Legacy permissions remain subject to the defined trust model.

PREPARING:
Enrollment initiation has been durably recorded.
Direct writes prohibited.

MANAGED:
Enrollment evidence has been authenticated and publication
has completed.
Direct writes prohibited; approved coordinator required.

UNCERTAIN:
Publication or recovery outcome cannot be established.
Direct writes prohibited.

INVALID:
Enrollment evidence is inconsistent or unauthenticated.
Direct writes prohibited.

## Unresolved implementation requirements

1. Establish a shared synchronization boundary for all writers.
2. Define durable ordering of database and policy-file updates.
3. Define external trust-record ownership and storage.
4. Define detection of deleted or rolled-back enrollment evidence.
5. Define authorized recovery without silent downgrade.
6. Specify crash-point and concurrency regression tests.
7. Verify compatibility with existing legacy ledgers.

## Acceptance criteria

No production enrollment activation until:

- State transitions are formally tested.
- Crash interruption tests pass.
- Concurrent writer tests pass.
- Missing-policy and altered-policy tests pass.
- Downgrade and deletion threat assumptions are documented.
- The full existing regression suite passes.
- No live-trading functionality is introduced.

## Implementation boundary

This document is a design contract only.

It must not be interpreted as proof that the described
protections are already implemented.
