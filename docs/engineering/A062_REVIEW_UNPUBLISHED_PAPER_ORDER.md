# A062 review an unpublished paper order

When a paper order commits and the process stops before publishing its
checkpoint, inspect the pending order under the independently pinned FREEZE.
Use the existing diagnostic and add the explicit review flag.

```sh
PYTHONPATH=app python -m ariyan_trading.paper_pending_diagnostic \
  --database /path/to/ledger.sqlite --anchor /path/to/anchor.json \
  --selector /path/to/active.json --expected-state-sha256 "$freeze_pin" \
  --checkpoint-key-file /path/to/checkpoint-key.bin --include-unpublished-order
```

The option requires an authenticated anchor at the immediately preceding
verified journal sequence. The diagnostic reads the order from the same
SQLite snapshot used to verify the journal. The output adds the request ID,
side, quantity, price, cash delta and units delta. Journal sequence and digest
identify the entry being reviewed. Treat this output as private.

`authenticated_by_anchor` is false for the displayed order. The anchor
authenticates the preceding checkpoint. Compare the order fields with the
independently retained paper order record. The diagnostic runs read-only
under FREEZE and grants no publication, clearance or trading authority.
