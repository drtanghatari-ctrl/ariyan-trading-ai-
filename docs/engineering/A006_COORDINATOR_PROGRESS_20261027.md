# A006 coordinator progress — 2026-10-27

Status: Experimental offline paper implementation.
A006 remains in progress. A007 has not started.

## Implemented

- Verified session balance reads remain bound to the authenticated
  sequence and digest established at opening.
- A persistent pending marker blocks checkpoint verification.
- The coordinator verifies an existing anchor before an explicit trade.
- Trade, journal commitment, and pending marker commit together.
- A second writer transaction checks for intervening journal changes
  and holds the SQLite writer lock during anchor publication.
- The pending marker is cleared only after successful publication
  and authenticated readback.
- No automatic enrollment, retry, repair, or recovery is performed.

## Observed Termux evidence

Full regression suite: 203 tests passed.
git diff --check: passed.

Coordinator integration covers BUY/SELL, verified reopening,
insufficient cash, duplicate requests, missing anchors, replacement
failure, and directory synchronization failure.

Four SIGKILL tests cover eight scenarios across DELETE and WAL:
before trade commit, after commit, after anchor replacement, and
after successful publication before marker clearance.

Three concurrency tests cover both DELETE and WAL:
a competing coordinator during pending publication, successive
trades through separate connections, and duplicate requests.

SIGKILL tests establish tested process-termination behavior.
They do not simulate storage-device power failure.

## Boundaries and remaining work

The default demo still uses the original float-based PaperEngine.
The Decimal coordinator is not integrated into that demo.

The coordinator accepts explicit paper quantities. It does not
implement portfolio risk sizing, fees, slippage, forecasting,
broker connectivity, or live trading authorization.

Uncoordinated DurableLedger methods remain available and do not
enforce this publication protocol. The pending marker blocks
verified opening and coordinated trades, not every possible writer.

Matching database-and-anchor rollback remains undetectable without
independent rollback-resistant evidence. Secure key custody,
rotation, revocation, authenticated recovery, complete attempt
history, and application lifecycle integration remain unfinished.

Further testing is required for commit errors, rollback errors,
marker-clearance failures, and other I/O boundaries.
Passing these tests does not certify production readiness.
