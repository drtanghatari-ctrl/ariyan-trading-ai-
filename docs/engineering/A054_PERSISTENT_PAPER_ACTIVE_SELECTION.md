# A054 recover the active paper state after reopening

Initialize a new selector once from an A050 state file and its independently
retained A051 pin. Keep the selector and state files in a trusted directory.

```python
create_paper_active_selection(
    selector_path, state_path, ledger_identity=ledger_id,
    expected_state_sha256=trusted_pin, checkpoint_key=checkpoint_key,
)

controller = PaperExecutionController.reopen(
    selector_path, ledger_identity=ledger_id,
    expected_state_sha256=trusted_pin, checkpoint_key=checkpoint_key,
    operator_public_key=trusted_operator_key,
)
```

The selector authenticates the active absolute state path and its pin
for the specified ledger. Reopen requires that the selector match the
separately retained pin and that the referenced state verify. Missing,
changed, or mismatched records stop reopening. An open controller also
checks the selector before each order and escalation.

On a successful signed escalation, the controller writes the successor,
synchronizes the replacement selector contents, and replaces the selector
within the same directory under the A053 lock. Retain the returned pin
independently before reopening. If the selector advances before that
independent copy is updated, reopening with the previous pin fails closed.
A failed replacement can leave an unused successor file. Inspect the
selector and separately retained pin before retrying.

This covers ordinary restart for a single controller. The selector and
independently retained pin do not advance as one transaction. Restoring both
together can still defeat the comparison. Cross-process serialization,
power-loss durability, and live trade control remain separate.
