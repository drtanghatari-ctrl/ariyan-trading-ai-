# A006 publication state machine

Status: Decision model only; coordinator not implemented.

Successful ordering:
READY -> COMMITTED -> PUBLISHING -> DURABLE.

A confirmed precommit abort ends in CANCELLED.
An uncertain outcome at any active boundary ends in UNCERTAIN.
All terminal states reject further events for that attempt.

The model consumes observations; it does not establish their truth.
READY does not mean approved, authenticated, or safe to trade.
A future coordinator must validate prerequisites before starting.

PUBLICATION_DURABLE requires successful completion of file fsync,
atomic replacement, and directory fsync. A failed directory fsync
leaves the attempt UNCERTAIN even if the replacement is readable.

A database commit and external anchor replacement are not atomic.
A committed database change is not undone by publication failure.
No automatic retry, repair, recovery, or re-anchoring is provided.
No persistent attempt log or restart reconciliation is implemented.

Remaining work includes coordinator integration, durable attempt
records, recovery authorization, key custody, independent rollback
resistance, and crash testing of the integrated workflow.

A006 remains in progress. A007 has not started.
