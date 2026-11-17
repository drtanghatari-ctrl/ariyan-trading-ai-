# A048 Multi-instrument portfolio: pre-registered protocol

Written 2026-11-17 BEFORE any portfolio result. Everything below is fixed; no parameter is searched.

## Universe and period
EURUSD, GBPUSD, USDJPY, XAUUSD, BTCUSD (US500 excluded: broker data hole). Daily bars on the COMMON calendar (dates on which all five have a bar, i.e. weekdays minus holidays; Bitcoin's weekend bars are not used, its Friday-to-Monday move is one bar). DEVELOPMENT period only: 2018-11-13 to 2025-11-11. The locked last 12 months are not touched by this protocol.

## Mechanics (simulation, no orders)
- Decide at a close, fill at the next open. Position held open-to-open.
- Sizing: each instrument gets an equal share of a portfolio volatility target of 10% a year: weight = signal x (10% / sqrt(252) / 5) / sigma, sigma = standard deviation of the last 60 daily close-to-close log returns. Gross notional capped at 3x equity.
- No-trade buffer: change a position only if the target differs from the current position by more than 25% of that instrument's full-size weight.
- Drawdown control (your 10% limit): equity is measured at closes against its peak. From 6% drawdown exposure tapers linearly to zero at 10%. At 10% the simulation goes flat (a "halt", reported) for 21 bars, then restarts with the peak reset. Halts are counted and shown.
- Costs (one-way, share of notional traded): EURUSD 1.0 bp, GBPUSD 1.0 bp, USDJPY 1.0 bp, XAUUSD 2.0 bp, BTCUSD 8.0 bp. Financing per calendar day on gross notional, both directions: 0.5 bp for forex and gold, 2.0 bp for Bitcoin. Stress case: all costs and financing doubled.
- USDJPY P&L in USD terms uses 1 - P0/P1 for a long (exact conversion of a JPY profit at the closing rate).

## Candidates (three, no others)
- A: sign of the 252-day return.
- B: sign of close minus the 200-day average.
- C: average of the signs of the 63-, 126- and 252-day returns.
Benchmarks: the same sizing, always long (a volatility-targeted basket); cash.
Signals start after 252 bars of history.

## Pass marks (from A045, applied to the BEST candidate and also reported for all)
1. Net return positive after base costs AND after doubled costs.
2. Deflated Sharpe probability >= 0.95. Trial count = 3 candidates + the 64 trials of the A044 EURUSD study (conservative), trial Sharpe variance from the three candidates.
3. Maximum drawdown <= 10% in the full period, with halts and every calendar year reported.
4. Positive profit on at least 3 of 5 instruments, and no instrument above 50% of total profit.
5. At least 100 position changes in total.
6. Beats the always-long basket on risk-adjusted return (Sharpe), otherwise trend rules add nothing.
FAIL means the rules are not shown to work; nothing goes to the locked holdout.

## Limits
Returns-based simulation, not the full order-level backtester; costs are assumptions, not this broker's measured costs; five markets is a small sample; diversification evidence in the literature comes from far more markets.
