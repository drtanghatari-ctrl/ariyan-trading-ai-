# Research protocol (A045)

Standard adopted from `trading_ai_technical_handoff.txt`: research, simulation and paper trading only; costs included; walk-forward; locked holdout; multiple-testing correction; independent risk gate; honest reporting. No profit is guaranteed and none is claimed.

## Decisions by the user (2026-11-13)
- Maximum acceptable loss (drawdown): **10%**.
- Focus timeframe: **Daily**.
- Final locked test: **last 12 months** of each dataset, used **once**.

## Pass marks (defaults; change only in writing before the next test)
1. Net positive after base costs AND after stressed costs (2x spread, swap stress).
2. Deflated Sharpe probability >= 0.95 using the registry's trial count.
3. Out-of-sample max drawdown <= 10% in every fold, with risk limits on.
4. Positive on at least half of instruments; no instrument above 50% of profit.
5. At least 100 out-of-sample trades in total.
6. Locked 12-month holdout positive net of costs, drawdown <= 10%, used once.
7. Then at least 3 months forward paper trading consistent with the simulator.
A strategy that fails any mark is not promoted. Orders to MT5 stay disabled until the user says otherwise.

## Tools
- `research_controls.py`: hash-chained experiment registry (tampering is detected), development/holdout split, once-only final test, contamination flag.
- `scorecard.py`: return, volatility, drawdown depth/duration/recovery, Sharpe/Sortino/Calmar, expected shortfall, yearly returns, trade statistics, block-bootstrap intervals, probabilistic and deflated Sharpe.

## Disclosure: EURUSD
A044 evaluated the full EURUSD D1 sample (sha256 `b91fd22f...`) before the holdout existed. Its last 12 months are therefore **contaminated**, recorded in `research/registry/experiments.jsonl` (trial count 64). EURUSD's true final test is forward paper trading. Other instruments have not been evaluated yet; their holdouts must be locked before any strategy work.

## Limits
The registry makes peeking visible; it cannot prevent it. Bootstrap shows sampling noise only. Backtests are descriptive, not evidence of future profit.
