# A058 inspect a pending paper checkpoint under FREEZE

Use the independently retained active state pin and the original raw
checkpoint key. All input paths must be existing local files.

```sh
PYTHONPATH=app python -m ariyan_trading.paper_pending_diagnostic \
  --database ledger.sqlite --anchor anchor.json --selector active.json \
  --expected-state-sha256 "$trusted_freeze_pin" \
  --checkpoint-key-file /private/path/checkpoint-key.bin
```

The command acquires the A055 selector lock, authenticates the selection
and FREEZE state, and reads the ledger using SQLite read-only access. It
requires a coordinator pending marker, verifies the local protected journal
chain, and verifies the anchor HMAC. It compares the anchor with the current
and previous locally verified journal tips.

| Report position | Meaning |
| --- | --- |
| `AT_PREVIOUS_VERIFIED_TIP` | The anchor matches the journal prefix before the latest entry |
| `AT_VERIFIED_JOURNAL_TIP` | The anchor matches the current journal tip while the pending marker remains |
| `OUTSIDE_EXPECTED_TIPS` | The anchor HMAC verifies but its sequence and digest match neither expected position |

A matching prior anchor authenticates its own tip. A058 does not independently
authenticate the pending suffix or authorize accepting it as a checkpoint.
The pending marker remains in place. The diagnostic does not clear it,
publish an anchor, or submit orders. A058 coexists with A020, whose normal
checkpoint inspection rejects a pending outcome.

The inspection can use the existing lock sidecar and SQLite-managed
sidecars. The lock coordinates participating paper controllers. Exit 0
returns a diagnostic, with all authority flags false. Exit 2 rejects
inspection without printing private input details.
