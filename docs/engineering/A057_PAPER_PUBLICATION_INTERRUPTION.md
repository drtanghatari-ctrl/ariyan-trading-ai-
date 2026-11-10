# A057 rehearse process termination during paper publication

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a056.py' -v
```

A057 extends the A056 disposable two-process rehearsal. The test terminates
the order process after the SQLite SELL commit and before the original
anchor writer runs. A signed FREEZE is already waiting on the selector
lock. When the terminated process releases the lock, FREEZE can activate.

The test checks that the committed SELL appears exactly once, the pending
publication marker survives, and the anchor still contains the original
checkpoint. Authenticated ledger reopening rejects the pending outcome.
The reopened FREEZE controller blocks another SELL before any SQL runs
and leaves the pending ledger and anchor intact.

The test covers process termination on the native A006 publication path
and shares A056's Windows skip. A pending outcome remains subject to
inspection before any recovery. The test does not exercise power loss,
repair the anchor, clear the marker, or replay the interrupted order.
