# A006-WB02-P3C3 — Independent Trust Authority Contract

Status: DESIGN ONLY — NOT IMPLEMENTED

## Purpose

Define the security requirements for independently retained
enrollment history in ARIYAN Trading AI.

This contract does not enable managed enrollment, trading,
broker connectivity, or capital authorization.

## Threat model

An attacker or failure may:

- Modify a ledger database.
- Replace or delete local policy files.
- Restore an older valid database and policy together.
- Interrupt enrollment between durable operations.
- Make the trust authority temporarily unavailable.
- Present a valid but obsolete authenticated record.

A locally stored HMAC-protected file alone does not provide
rollback resistance against coordinated restoration.

## Required identity binding

Each authoritative enrollment record must bind:

- Canonical ledger UUIDv4.
- Enrollment sequence.
- Historical journal digest.
- Writer-policy version.
- Enrollment generation or monotonic revision.
- Authority identity and record version.

## Authenticity

Records must be authenticated using an explicitly defined
key-management and verification protocol.

Authentication must not be confused with freshness.

## Freshness and continuity

The authority must preserve durable enrollment history.

A previously enrolled ledger must not silently become LEGACY.

An older valid record must not replace a newer authoritative
record without detection.

The design must specify how monotonic revisions are enforced.

## Authority independence

The authoritative record must not share the same rollback
failure domain as the ledger database and policy file.

An ordinary local file does not meet this requirement by itself.

The authority's storage, access controls, backup policy,
and recovery model remain to be selected and verified.

## Lookup outcomes

The interface must distinguish:

- PRESENT: authenticated enrollment evidence is available.
- ABSENT: an authoritative history-complete lookup establishes
  that no enrollment record exists for the ledger.
- UNAVAILABLE: the authority cannot provide a reliable answer.
- INVALID: evidence is malformed, unauthenticated, stale,
  contradictory, or otherwise unacceptable.

ABSENT must not be inferred from a missing local file.

UNAVAILABLE and INVALID must never authorize legacy writes.

## Enrollment ordering

Before managed publication, the implementation must define:

1. A synchronization boundary shared with ordinary writers.
2. A durable preparation marker that blocks direct writes.
3. An authoritative enrollment-history commitment.
4. Authenticated writer-policy publication.
5. Verified completion and managed-state recognition.

Crash recovery must account for interruption after every step.

## Recovery

Recovery requires explicit operator authorization.

Automatic downgrade, silent re-enrollment, and automatic
replacement of conflicting authoritative evidence are prohibited.

Recovery decisions must be auditable.

## Security limitations

The current codebase does not implement this independent
trust authority.

The pure P3C2 evidence classifier relies on caller-established
authentication and authority assumptions.

It must not be treated as proof of rollback resistance.

## Acceptance criteria

Before integrating this authority into ledger enforcement:

- Authority ownership and storage are specified.
- Authentication and key management are specified.
- Monotonic revision enforcement is tested.
- Coordinated rollback and deletion tests pass.
- Authority-unavailability behavior fails closed.
- Crash and concurrent-writer tests pass.
- Existing legacy-ledger compatibility is verified.
- Full regression suite passes.
- No live-trading functionality is introduced.

## Implementation boundary

This document establishes requirements only.

No enrollment activation or trading authorization follows
from its creation.
