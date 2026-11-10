# A046 require and record an RFC 3161 timestamp during replay

After the frozen evaluation window closes, supply the original receipt,
the CA file, and its independently obtained SHA-256 as a group.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv --output evaluation-report.json \
  --timestamp-receipt plan.tsr --timestamp-ca-file cacert.pem \
  --expected-timestamp-ca-sha256 "$trusted_ca_sha256" --timestamp-tsa-cert tsa.crt
```

The TSA signer certificate is optional and untrusted. A045 verifies the
receipt against the same loaded plan used for replay. A failed check stops
the command before it reads candles or opens the report.

An A046 report includes `plan_timestamp_check`, with the plan fingerprint,
the exact receipt and CA file fingerprints, the signed UTC epoch time, and
the verification status. To reproduce it, use `--verify-report`,
`--expected-plan-sha256`, and the same timestamp options. Use the same source
and witness recording flags if those records were included at creation.
Reports created without timestamp options retain their existing format.

The timestamp attests the fingerprint at the signed time. It does not attest
public publication, so `plan_publication_time_verified` remains false.
The receipt does not establish candle provenance or prospective performance.
The Predictability Gate remains `NO_TRADE`.
