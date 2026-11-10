# A060 clear one signed, already-published pending marker

Use only the A059 clearance case where the authenticated anchor already
matches the journal tip. The operator reviews the clearance binding and
signs the A059 intent.

```python
result = clear_published_pending_marker(
    database, anchor, selector, intent, signature,
    expected_state_sha256=trusted_freeze_pin,
    checkpoint_key=checkpoint_key,
    operator_public_key=trusted_operator_key,
)
```

The explicit offline API uses the A055 selector lock and an existing SQLite
database opened read-write. Within a FULL or EXTRA synchronous write
transaction it checks the FREEZE pin and signed intent against fresh
checkpoint evidence. It checks expiry using the local clock after taking
the locks. A previous or divergent anchor is ineligible.

The transaction deletes the one matching pending marker and requires
exactly one changed row. It re-verifies the journal and existing anchor
through A006 before commit. The operation preserves the journal, anchor,
and active FREEZE. It does not resubmit the trade. The A059 assessment
remains read-only.

An exception before commit rolls back the write transaction. If the commit
outcome is uncertain, the caller receives `PendingClearanceUncertain` and
must inspect the checkpoint and pending marker before deciding what to do.
There is no automatic retry. An already-cleared marker cannot be cleared
again with the same approval.

This is the narrow published-anchor paper case. Recovery when the anchor
is still at the previous tip, operator key enrollment, independent rollback
resistance, and live trading authority are separate.
