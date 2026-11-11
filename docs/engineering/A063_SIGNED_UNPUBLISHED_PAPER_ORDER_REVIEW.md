# A063 assess a signed unpublished paper order review

Run the A062 diagnostic with `--include-unpublished-order` to get the
`unpublished_order_review_sha256`. It binds the ledger identity, active
FREEZE pin, pending attempt, journal tip and preceding anchor.

Build the intent with `VERSION` and `ACTION` from
`ariyan_trading.paper_unpublished_order_review`, the reported
`unpublished_order_review_sha256`, and a UTC `expires_at_ms`. Take
`request_id`, `side`, `quantity` and `price` from the independently
retained paper order. Use decimal strings for quantity and price.

The operator signs the bytes returned by
`unpublished_order_review_payload(intent)` with Ed25519. Call
`assess_unpublished_order_review` with the intent and signature, a separately
trusted operator public key, the independently retained FREEZE pin, the
checkpoint key and the current UTC epoch milliseconds as `as_of_ms`.

The assessment rereads the evidence under FREEZE, verifies the signature and
expiry, compares the order fields, and recomputes the ledger deltas from the
signed order. The result records agreement at inspection time. The anchor
authenticates the preceding checkpoint. This read-only assessment grants no
authority to publish, clear a marker or trade.
