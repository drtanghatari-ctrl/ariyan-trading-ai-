# A006 — Authenticated Checkpoint Snapshot Safety

Status: Implemented and locally regression-tested;
full A006 milestone certification remains pending.

## Change

Checkpoint verification now requires an active SQLite
transaction on the supplied connection.

Verification fails closed when the transaction is absent.

Existing checkpoint tests establish a transaction before
invoking the verifier.

## Verification evidence

Local Termux execution on 2026-10-22:

- Snapshot safety test: passed.
- Checkpoint verification tests: 5 passed.
- Full regression suite: 138 passed.
- Full suite exit code: 0.
- git diff --check: no reported errors.

## Security boundaries

- The caller owns transaction lifetime and consistency.
- An active transaction does not independently prove that
  a read snapshot has already been established.
- The verifier does not prevent caller writes during the
  transaction.
- The authenticated anchor does not provide independent
  rollback resistance if the database and anchor can both
  be restored together.
- Key custody, rotation, recovery authorization, and
  coordinated anchor publication remain unresolved.
- This change does not establish production integration
  into the complete ledger lifecycle.
- Local passing tests are not production certification.

## Continuation

Review the staged diff, confirm the regression suite,
and commit only the intended source, tests, and record.
Do not advance to A007 solely on this evidence.
