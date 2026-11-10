# A052 prepare a signed paper safety escalation

An operator signs the bytes from `escalation_payload(intent)` with their
Ed25519 private key. The intent contains exactly these fields.

| Field | Value |
| --- | --- |
| `version` | `ARIYAN-A052-PAPER-STATE-ESCALATION-V1` |
| `ledger_identity` | Expected ledger UUIDv4 |
| `current_state_sha256` | Current A051 state pin, lowercase SHA-256 |
| `target_state` | `STOP` or `FREEZE` |
| `expires_at_ms` | Exclusive expiry in UTC epoch milliseconds |

The signed bytes are the ASCII version and a NUL separator followed by
compact ASCII JSON with sorted keys. The raw 32-byte operator public key
must come from independently trusted configuration.

```python
next_pin = prepare_paper_escalation(
    current_path, next_path, intent, signature,
    ledger_identity=ledger_id, expected_current_sha256=current_pin,
    checkpoint_key=checkpoint_key, operator_public_key=trusted_operator_key,
    as_of_ms=current_utc_ms,
)
```

The function verifies the intent, its expiry against the supplied clock,
and the current pinned A050 file. It permits NORMAL to STOP or FREEZE,
and STOP to FREEZE. It creates a new file exclusively and returns its pin
without changing the current file or selecting which file governs orders.
The current paper configuration stays active until its caller explicitly
adopts a different state file and pin.

This is an offline preparation API. It provides no operator enrollment,
monotonic pin store, atomic activation, or coordination with in-flight
orders. It grants no trading authority and has no resume operation.
