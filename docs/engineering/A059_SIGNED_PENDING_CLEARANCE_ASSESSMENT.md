# A059 assess a signed pending-marker clearance intent

Add `--include-clearance-binding` to the A058 diagnostic to obtain
`clearance_binding_sha256`. The fingerprint covers the ledger UUID, active
state pin, pending attempt marker, journal tip, anchor, and their relationship.
The ordinary A058 report is unchanged when the flag is omitted.

The operator independently reviews the report. A059 handles only
`AT_VERIFIED_JOURNAL_TIP`, where the checkpoint is already authenticated
against the current journal and the pending marker remains.

Sign the bytes from `clearance_payload(intent)` with the operator's Ed25519
private key. The signed object has exactly these fields.

| Field | Value |
| --- | --- |
| `version` | `ARIYAN-A059-PAPER-PENDING-CLEARANCE-V1` |
| `action` | `CLEAR_PUBLISHED_PENDING_MARKER` |
| `clearance_binding_sha256` | Fingerprint from the A058 diagnostic |
| `expires_at_ms` | Exclusive expiry in UTC epoch milliseconds |

`assess_pending_clearance` verifies against an independently supplied operator
public key, checks expiry at the supplied time, and obtains fresh A058
evidence under the selector lock. It rejects a changed attempt or any anchor
position other than the current tip. Success confirms the signature and the
evidence match at inspection time.

A059 does not clear the pending marker, rewrite the anchor, or authorize
a write. Future clearance would require rechecking the same signed intent
and evidence inside the lock and write transaction. An anchor at the prior
tip requires a separate recovery design.
