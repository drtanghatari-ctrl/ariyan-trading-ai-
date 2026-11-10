# A061 rehearse signed clearance after paper anchor publication

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a056.py' -v
```

The A056 rehearsal now also pauses the order process after the native A006
anchor writer returns and before the coordinator can clear its pending
marker. The test kills that process while signed FREEZE activation waits
for the selector lock. All files and keys are disposable fixtures.

The parent verifies that the SELL committed once, the authenticated anchor
matches journal sequence two, and the pending marker still blocks
authenticated reopening. Under the active FREEZE, the parent signs the
inspection binding and invokes the A060 clearance API.

The ledger then reopens with authenticated balances and exactly the two
original orders. The marker is gone, the anchor and FREEZE files are
byte-identical, and FREEZE still blocks a subsequent SELL.

This covers process termination on the native A006 publication path. It
shares A056's Windows skip. Power-loss durability requires separate testing.
