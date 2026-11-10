# A038 reproduce a saved validation report

Use the original frozen plan, original candle CSV, saved A037 report, and a
copy of the plan fingerprint recorded separately before the window began.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv \
  --verify-report evaluation-report.json \
  --expected-plan-sha256 "$recorded_plan_sha256"
```

The command checks the independently supplied reference value against the
verified plan before reading candles. It then reruns A037 and compares the
complete report bytes. Keep the original report serialization and CSV bytes.
Changes such as reformatting the JSON or converting the CSV line endings cause
verification to fail. The command opens the saved report for reading only.

Success prints `REPORT_REPRODUCED` followed by `CRITERIA_MET` or
`CRITERIA_NOT_MET`. A failing evaluation can reproduce successfully.
Verification errors exit with status 2.

The separately supplied digest is a comparison value. The command cannot
authenticate when it was recorded, the declared engine revision, or the candle
source. Reproduction confers no trading authority. A027 remains `NO_TRADE`.
