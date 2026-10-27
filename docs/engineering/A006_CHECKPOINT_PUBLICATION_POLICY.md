# A006 — Checkpoint Publication and Recovery Policy

Status: Experimental paper coordinator implemented; full A006 certification pending.
Date: 2026-10-22

## Established implementation

- SQLite ledger transactions are committed independently of
  external authenticated checkpoint files.
- Journal commitments are validated cryptographically.
- Anchor replacement uses a temporary file, fsync, atomic
  replacement, and directory fsync.
- Checkpoint-verified ledger sessions are read-only.
- Missing, stale, divergent, or unauthenticated anchors are rejected.

## Failure states

1. Database and authenticated anchor agree:
   verification may proceed, subject to all other validation.

2. Database commit succeeds, anchor publication does not:
   checkpoint verification must fail closed. Do not infer that
   the discrepancy is harmless.

3. Anchor publication is interrupted before replacement:
   the previous anchor may remain. Verify it against the
   actual journal; reject mismatches.

4. Anchor replacement succeeds but durability is uncertain:
   re-read and authenticate the persisted anchor. Do not
   assume success from an interrupted operation.

5. Journal and anchor are both restored to an older matching
   state: local HMAC verification alone cannot detect this.
   Independent rollback-resistant evidence is required.

6. Anchor is missing, corrupt, or authenticated with the
   wrong key: reject verification. Never regenerate silently.

## Mandatory invariants

- No automatic checkpoint repair or re-anchoring.
- No acceptance of unexplained sequence or digest mismatch.
- No key material embedded in source control or reports.
- No production trading authorization based solely on
  an unverified or stale checkpoint.
- Explicit recovery authorization and independently
  validated evidence are required before any recovery.
- Preserve original evidence and audit records.
- Failure injection and restart tests are required before
  any publication implementation can be certified.

## Remaining engineering work

- Extend the implemented publication state machine as lifecycle requirements evolve.
- Integrate the tested paper coordinator ordering into the application lifecycle.
- Define authenticated recovery authorization.
- Extend the implemented fault-injection and SIGKILL tests to additional failure boundaries.
- Establish key custody, rotation, and revocation.
- Establish independent rollback resistance.
- Verify integration with the complete trading lifecycle.

## Certification boundary

This document specifies safety requirements. The experimental paper coordinator implements tested publication ordering
and persistent pending markers. Automated recovery and production-ready
checkpoint management remain unimplemented.

A006 remains in progress. A007 has not started.
