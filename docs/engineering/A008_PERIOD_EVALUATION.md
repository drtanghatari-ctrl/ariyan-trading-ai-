# A008 — fixed-parameter chronological evaluation

Based on checkpoint 4605f51. Adds evaluation.py and its tests without editing
A007, ledger, authorization, default demo or CI. No network or live orders.

## Contract

`evaluate_periods(dataset, config, periods=3, stress_fee_bps="20",
stress_slippage_bps="10")` runs the existing A007 SMA test strategy with fixed
parameters across 2..20 contiguous, disjoint chronological periods. Every input
bar is used exactly once per scenario. Equal-sized periods are used with any
remainder assigned one bar at a time to earlier periods. Each period requires
at least long_window + 1 candles and includes its own cold-start warmup.

Cash, positions and signals reset at each boundary. This measures independent
restarts, not continuous deployment or one compounded account. The last
signal is not filled beyond the period; final positions remain marked without
liquidation costs. Baseline and stress results are correlated, not independent
confirmation. Stress fee and slippage must both be at least their base values,
with at least one strictly higher. Costs may change sizing and subsequent trade
paths; higher costs need not produce monotonically lower returns.

No optimization or training occurs. Caller prior access to the data is unknown:
these results are descriptive historical evaluation, not established out-of-sample
validation, walk-forward selection, strategy approval or evidence of profitability.
Choosing period boundaries or parameters after viewing results can bias findings.
The report counts positive/negative/flat periods, but assigns no passing grade,
minimum adequate sample size, significance level or authority to trade.

Reports retain per-period base/stress config, summary, and buy-and-hold comparison,
plus period index/time boundaries. They omit full trade/curve arrays; A007 remains
available for detailed replay. The recorded hash identifies the full original input
bytes, not separately serialized subsets. Source and symbol are caller labels;
no independent data authenticity is claimed. Buy-and-hold is full-allocation and
not risk matched. All A007 execution and liquidity limitations still apply.

## Real-data integration smoke only

```
mkdir -p work
PYTHONPATH=app python -m ariyan_trading.evaluation \
  --csv examples/a007/BTCUSDT-1h-2024-01-01.csv \
  --format binance-spot --timestamp-unit ms \
  --symbol BTCUSDT --interval-ms 3600000 \
  --source 'Binance public spot klines BTCUSDT 2024-01-01 1h; smoke only' \
  --as-of-ms 1704153600000 --periods 3 \
  --output work/a008-smoke.json
```

This partitions 24 real candles into three eight-bar periods. With five warmup
bars per period, this is deliberately only an integration smoke check. It cannot
support an investment conclusion. Larger independently reserved datasets are a
separate next task. Output files are exclusively created and never overwritten.
An explicit cutoff is required for reproducibility.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a008.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Eleven tests cover complete partition coverage and chronology; exact agreement
with independent A007 runs; future-period and prior-period isolation; reset and
warmup boundaries; counts/provenance; hostile Decimal context; invalid input and
stress costs; smallest valid dataset; deterministic fresh-process real-data smoke;
input/report no-overwrite; and failure without report creation.

A006's known expected failure remains unresolved. No live-readiness claim is made.
