# A042 verify a witness receipt for a frozen plan

A witness receives the A036 plan fingerprint and signs it with the UTC
millisecond time at which the witness observed it. The verifier checks the
receipt against an expected Ed25519 public key obtained through a separate
trusted channel. The witness must use its own trusted clock and must not
sign a timestamp supplied by the plan operator.

The receipt is a UTF-8 JSON object with exactly these fields.

| Field | Value |
| --- | --- |
| `version` | `ARIYAN-A042-PLAN-WITNESS-V1` |
| `plan_sha256` | A036 fingerprint, 64 lowercase hex characters |
| `observed_at_ms` | Witness observation time, UTC epoch milliseconds as a JSON integer |
| `signature_hex` | Raw Ed25519 signature, 128 lowercase hex characters |

The signer uses Ed25519 over three ASCII lines, each terminated by one LF.
The lines contain the version, the exact fingerprint, and the timestamp in
base ten without leading zeros. The Python `witness_payload` function
produces these bytes.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_witness \
  --plan plan.json --receipt witness-receipt.json \
  --witness-public-key-hex "$trusted_witness_public_key"
```

The key is the raw 32-byte Ed25519 public key in lowercase hex. Verification
requires the same `cryptography` dependency used by A006. A match prints
`SIGNED_PRE_WINDOW_RECEIPT_VERIFIED` in a JSON result with the observation
time and key fingerprint. The signed time must be at or after the plan's
declared creation time and strictly before its evaluation window begins.
Invalid receipts exit with status 2.

This is an ATAI receipt format. The verifier does not operate a witness
service, enroll keys, determine whether a witness is independent, or
authenticate its clock. Successful verification establishes what the
supplied key signed. Trust in that timestamp depends on how the key and
witness were established. A042 operates independently of evaluation and
keeps the Predictability Gate at `NO_TRADE`.
