# A043 require a signed pre-window receipt before replay

Add both witness options to require A042 verification during report creation:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv --output evaluation-report.json \
  --witness-receipt witness-receipt.json \
  --witness-public-key-hex "$trusted_witness_public_key"
```

The same pair is accepted during report reproduction with `--verify-report`
and `--expected-plan-sha256`. A missing option or invalid receipt stops the
operation before it reads candles or opens the report. The receipt and key are
optional as a pair for compatibility. They can be combined with
`--require-engine-source` or `--record-engine-source`.

In Python, pass `witness_receipt_path` and `witness_public_key_hex` together
to `evaluate_plan`. This is a precheck, so report bytes stay compatible
with A038 reproduction. Keep the receipt and its independently established
key with the evaluation evidence. A042's witness trust assumptions still
apply. The Predictability Gate continues to return `NO_TRADE`.
