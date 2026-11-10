# A037 evaluate a frozen validation window

After the evaluation window closes, supply the frozen A036 plan and a CSV
covering exactly that window. The CSV must use the market format and timestamp
unit in the plan and contain every candle from the inclusive start through the
last candle that closes at the exclusive end for candle opens.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --csv evaluation-window.csv --output evaluation-report.json
```

A037 verifies the plan fingerprint, checks that the window has ended against
the local clock, and loads the candle bytes through A007 using the window end
as the data cutoff. A008 then runs the frozen configuration and stress costs
across the specified periods. Both scenarios must meet the minimum positive
period count. Within each scenario, every period must meet the minimum filled
order count and the maximum close-marked drawdown, using the A008 summary.

The report includes the plan fingerprint, declared code commit, candle file
SHA-256, A008 metrics, and each criterion's outcome. Repeating the evaluation
with the same engine, plan and candle bytes produces the same report.
The command creates the output exclusively. Exit status zero means a report
was written. Use the `criteria_met` field for the recorded outcome.

The evaluator runs the locally installed A007/A008 code. The declared commit,
market provenance, and publication time still require independent verification.
Meeting the recorded criteria does not establish prospective validation or
trading authority. A027 continues to return `NO_TRADE`.

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a037.py' -v
```
