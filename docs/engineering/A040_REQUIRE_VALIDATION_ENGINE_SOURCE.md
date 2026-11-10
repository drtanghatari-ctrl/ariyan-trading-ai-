# A040 require the declared source revision before evaluation

Add `--require-engine-source` to the A037 creation command:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv \
  --output evaluation-report.json --require-engine-source
```

Or apply the same requirement to A038 report reproduction:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv \
  --verify-report evaluation-report.json \
  --expected-plan-sha256 "$recorded_plan_sha256" --require-engine-source
```

In both modes, a missing or mismatched source causes exit status 2 before
the command reads candles or opens the report. The Python
`evaluate_plan(..., require_engine_source=True)` argument applies the same
requirement. Existing calls without the option keep their behavior.

A039 checks the local source bytes at the time of inspection. A037 report
bytes stay compatible with A038 and carry no record of the precheck. The
precheck does not attest the Python runtime, establish when the plan was
published, or authenticate the candle source. A027 continues to return
`NO_TRADE`.
