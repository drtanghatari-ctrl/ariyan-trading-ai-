# Idea gate: what a new strategy idea must show before it earns a test

Written 2026-11-18, after A044, A047 and A050 found no usable edge. Every test spends a little of our evidence budget (the registry's trial count feeds the deflated Sharpe mark), so ideas are screened on paper first. Orders stay disabled.

## Gate (all required, in this order, before any backtest)
1. Reason: one paragraph, written before looking at data: who is on the other side of the trade and why the pattern should persist after costs. "It fit the past" is not a reason.
2. Cost arithmetic: expected gross edge per trade and trades per year, against this broker's measured round-trip cost and financing (`research/costs/`). The expected edge must be at least 3x the cost per trade, otherwise stop here. Fast strategies must clear this much harder than Daily ones.
3. Independent data: the decision test uses data no earlier study examined (LiteFinance 2014-08 to 2018-11 is spent for the trend family; the locked holdouts are untouched) or forward paper trading. Re-running the same period only counts as consistency.
4. Pre-registration: markets, period, parameters, costs and pass marks written and committed before the run, one run, results logged in the registry.
5. Trial budget: after A050 the registry holds 70 counted trials. Each new candidate raises the bar for the next, so candidates per protocol stay at three or fewer.
6. Sample size reality check (below). If the test cannot settle the question, say so in the protocol instead of pretending.
7. After a PASS only: the locked holdout once, then at least 3 months of forward paper trading.

## Sample size reality check
To show a true Sharpe ratio of 0.5 at the 5% level with 80% power needs roughly (1.64 + 0.84)^2 / 0.5^2 = 25 years of independent returns from one return stream. Our fresh period is 2.8 years, so a single-stream test could not confirm even a decent edge. Breadth (many independent markets) and forward evidence are the only ways to get there; correlated USD pairs do not count as independent. A FAIL on a short sample means "not demonstrated", never "proven worthless".

## Ideas on the shelf (not tests, only notes on what would have to be true)
- Cross-sectional currency momentum (long strongest, short weakest). Needs a stated reason it differs from the trend rules that failed, and the same swap costs apply.
- Carry. Needs historical swap or interest-rate series; the broker publishes only today's snapshot, so it cannot be tested honestly yet.
- Volatility-targeted gold plus Bitcoin only. Fresh-period data for Bitcoin starts in 2018, so there is no clean period.
- Intraday strategies. Costs per trade are many times higher; item 2 usually ends the idea.
- Forecasting models (Kronos, TimesFM): failed A047; only a forward paper record could revive them.
Nothing on this shelf is recommended yet.
