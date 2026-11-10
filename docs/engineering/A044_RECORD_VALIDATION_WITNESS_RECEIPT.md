# A044 record the verified witness receipt

Add `--record-witness-receipt` to the A043 command to record which receipt
was checked during report creation:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv --output evaluation-report.json \
  --witness-receipt witness-receipt.json \
  --witness-public-key-hex "$trusted_witness_public_key" --record-witness-receipt
```

The versioned A044 report includes the signed observation time, plan
fingerprint, witness key fingerprint, verification status and receipt
fingerprint. The receipt fingerprint is the SHA-256 of the verified receipt
object serialized as compact ASCII JSON with sorted keys, no spaces and no
trailing newline. It covers all four receipt fields, including the signature.
Whitespace or object field order in the original receipt file may differ.

To reproduce the A044 report, use the same witness options with
`--verify-report` and the independently recorded `--expected-plan-sha256`.
Keep the original receipt available. Replacing it with a different valid
receipt changes the report. If creation included `--record-engine-source`,
include it again to reproduce both records. In Python, the corresponding
witness option is `record_witness_receipt=True`.

Existing reports keep their format when the new option is omitted.
The report records verification against the supplied key. The witness and
clock still require independent trust. The report itself is unsigned,
`plan_publication_time_verified` remains false, and A027 remains `NO_TRADE`.
