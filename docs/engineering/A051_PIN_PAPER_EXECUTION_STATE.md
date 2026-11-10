# A051 pin the expected paper execution state

The A050 MAC authenticates a state record. A051 can also require that the
authenticated bytes match the expected record for this run. After creating
or independently approving the expected state, retain its SHA-256 in
separately protected configuration. Keep that value across restarts.

```python
execute_governed_paper_trade(
    ledger, action, request_id, quantity, price,
    anchor_path=anchor_path, key=checkpoint_key,
    execution_state_path=state_path,
    expected_execution_state_sha256=trusted_state_sha256,
)
```

A051 compares the pin with the same bytes it authenticates and parses.
A mismatch stops the order before the coordinator is called. A matching
pin still requires the A050 MAC and ledger identity to verify. Existing
callers can continue using the unpinned A050 path.

Record the pin from the expected state at approval time. Computing it from
whatever file is present at order time provides no rollback check. A051
rejects a restored older file when the pin still identifies the expected
current file. If both are restored together, the comparison can pass.
Monotonic authority, authorized transitions, and coordination with in-flight
orders remain future work. This check applies only to the offline paper path.
