# A045 verify an RFC 3161 plan timestamp offline

Supply the original frozen plan, the DER timestamp response, and a trusted
timestamp CA file. Obtain the expected SHA-256 of that CA file through a
trusted channel independent of the receipt. The optional signer certificate
helps OpenSSL construct the chain and is treated as untrusted input.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_timestamp \
  --plan plan.json --receipt plan.tsr \
  --ca-file cacert.pem --expected-ca-sha256 "$trusted_ca_sha256" \
  --tsa-cert tsa.crt
```

A045 calls OpenSSL to verify the timestamp response against the exact A036
plan fingerprint and the pinned CA file. It requires a SHA-256 imprint and
a signed UTC time at or after declared plan creation and strictly before the
window opens. It reads bounded snapshots and performs no network requests.
OpenSSL's normal certificate validity checks apply.

Success returns `RFC3161_PRE_WINDOW_TIMESTAMP_VERIFIED` with the plan
fingerprint, signed time in UTC epoch milliseconds, and the SHA-256 values of
the receipt and CA file. Errors exit with status 2. Retain the original plan,
request, response, certificates, and independently obtained CA fingerprint.

This command handles RFC 3161 separately from A042 Ed25519 receipts. Trust
in the time depends on the timestamp authority and its clock. The command
does not read candle data, produce evaluation results, or change the trade
decision.

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a045.py' -v
```
