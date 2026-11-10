# A036 prospective validation plan

Prepare a JSON specification before the first candle of the evaluation window.
Record the full Git commit for the A007 strategy and A008 evaluator and use the
existing replay configuration fields.

| Object | Required fields |
| --- | --- |
| Root | `code_commit`, `market`, `window`, `config`, `stress_costs`, `periods`, `criteria` |
| Market | `symbol`, `source`, `interval_ms`, `input_format`, `timestamp_unit` |
| Window | `start_ms` inclusive, `end_ms` exclusive for candle opens |
| Config | `opening_cash`, `fee_bps`, `slippage_bps`, `max_buy_fraction`, `max_position_fraction`, `short_window`, `long_window` |
| Stress costs | `fee_bps`, `slippage_bps` |
| Criteria | `min_positive_periods`, `min_filled_orders_per_period`, `max_close_drawdown_pct` |

Use UTC epoch milliseconds for the window. Both boundaries must align to the
interval. Encode cash, costs, fractions and percentage thresholds as unsigned
decimal strings. Use JSON integers for counts, timestamps, intervals and
moving-average windows.

All criteria apply separately to the base and stress scenarios. A positive
period has `net_marked_pnl > 0`. Each period must meet the order-count minimum
and the close-marked drawdown maximum. A008 resets the portfolio and warmup
for each period. The caller selects all thresholds. Structural checks cover
replay feasibility. Statistical adequacy and execution realism require
separate evaluation.

```sh
PYTHONPATH=app python -m ariyan_trading.validation_plan freeze spec.json plan.json
PYTHONPATH=app python -m ariyan_trading.validation_plan verify plan.json
```

The freeze command uses the local clock and creates the output exclusively.
Both commands print the SHA-256 of the canonical ASCII JSON payload, using
sorted keys and compact separators, with the digest field excluded. Compare
the printed digest to a copy recorded independently before the window starts.
A local clock and a self-contained digest provide no independent timing or
authenticity. Verification checks the record and digest, with the code commit
and source label treated as caller declarations.

A036 prepares a plan. Evaluation, binding the result to the frozen plan,
verifying when it was published, and assessing any statistical evidence are
separate steps. The A027 Predictability Gate continues to return `NO_TRADE`.

```sh
PYTHONPATH=app python -m unittest discover -s tests -p 'test_validation_plan_a036.py' -v
```
