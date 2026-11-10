# A056 rehearse FREEZE against real paper checkpoint publication

Run the two-process test using a disposable SQLite paper ledger:

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a056.py' -v
```

The test seeds two units and submits a SELL through a persistent A055
controller in a child process. It pauses the real coordinator after the
SQLite trade commit and before the anchor write. The parent observes the
pending marker and the old anchor. It then requests a signed FREEZE and
checks that activation waits while publication is paused.

When released, the child performs the actual anchor write and coordinator
readback. The parent activates FREEZE, reopens the controller with the new
pin, and authenticates the ledger at checkpoint sequence two. A subsequent
SELL is denied with zero SQL statements and unchanged ledger and anchor
contents. The only instrumented checkpoint operation is the pause before
the original anchor writer runs.

This rehearsal uses synthetic prices and the native A006 anchor writer.
The test skips Windows, where that writer's native publication path is a
separate checkpoint. It does not simulate power loss or provide live
trading or execution evidence.
