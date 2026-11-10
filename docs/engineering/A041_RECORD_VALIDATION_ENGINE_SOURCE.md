# A041 record the replay source check in the evaluation report

Add `--record-engine-source` when creating a report to require the A039
source comparison and include the checked paths in the output:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv \
  --output evaluation-report.json --record-engine-source
```

Use the same flag when reproducing this report:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv \
  --verify-report evaluation-report.json \
  --expected-plan-sha256 "$recorded_plan_sha256" --record-engine-source
```

The A041 report adds `engine_source_check` with status
`LOCAL_SOURCE_BYTES_MATCH` and the covered paths. The comparison uses the
commit named in `declared_code_commit`. A mismatch stops replay before
the command reads candles. The Python argument is `record_engine_source=True`.

Calls without the record option keep the A037 report format, including when
using `--require-engine-source`. The A041 record describes a source-file
comparison. It is unsigned and does not attest the Python runtime or
which bytecode executed, so `code_commit_verified` remains false. The
A027 decision remains `NO_TRADE`.
