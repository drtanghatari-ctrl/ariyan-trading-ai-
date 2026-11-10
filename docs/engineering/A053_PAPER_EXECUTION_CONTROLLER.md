# A053 activate a signed escalation in one paper controller

Construct one controller per paper ledger from an independently retained
A051 pin and trusted operator key. Route that controller's paper orders
and A052 escalation intents through the same instance.

```python
controller = PaperExecutionController(
    current_path, ledger_identity=ledger.ledger_identity,
    expected_state_sha256=current_pin, checkpoint_key=checkpoint_key,
    operator_public_key=trusted_operator_key,
)

next_pin = controller.activate_escalation(next_path, intent, signature)
controller.execute(
    ledger, "SELL", request_id, quantity, price, anchor_path=anchor_path,
)
```

Activation checks expiry against the local clock after acquiring the lock.
It prepares the successor with A052 and selects its path and pin only after
preparation succeeds. A failed escalation keeps the previous selection.
Later requests verify the selected file and pin through A051 before entering
the checkpoint coordinator. A stale intent signed for the previous pin
cannot activate again on this controller.

The same lock spans each order and its checkpoint publication. If an order
already holds the lock, activation waits for that order to return or raise.
There is no cancellation of an in-progress order or priority among waiting
threads. Callers remain responsible for SQLite connection ownership.

Activation is process-local to the instance. Persist the returned pin
through separate trusted configuration before reopening with the successor.
Independent controller instances, direct callers, and other processes do not
share this lock or state selection. This paper API does not provide a
durable activation transaction, monotonic recovery, or live trade control.
