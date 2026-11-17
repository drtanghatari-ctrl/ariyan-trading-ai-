# A050 Broader-universe trend portfolio on LiteFinance data: pre-registered protocol

Written 2026-11-17 BEFORE any A050 strategy result. Everything below is fixed; no parameter is searched.
Question: do the three A048 trend rules make money after this broker's measured costs, on a wider market set,
in a period nobody has examined? This is the only question. Orders stay disabled; this is simulation.

## Data (nothing else is used)
LiteFinance demo Daily exports of 2026-11-17, cleaned by `research/prepare_lf.py` (short Sunday stub bars merged into Monday). Instruments: EURUSD, GBPUSD, USDJPY, AUDUSD, USDCAD, USDCHF, NZDUSD, XAUUSD (the `_o` ECN symbols) and BTCUSD. Silver is excluded (its measured swap of -82% a year is not credible). US500 stays excluded (broker data hole).
Final holdout: bars from 2025-11-12 are locked in the registry for all nine and are NOT used here.

## Two segments
- F (fresh, decides the verdict): the 8 non-crypto instruments on the common calendar 2015-01-21 to 2018-11-12. This period was never examined by any earlier study. Scoring starts after a 252-bar warm-up (about early 2016), so about 2.8 years are scored. Bitcoin is not in F (its history starts 2018-02).
- E (examined market, consistency check only): all 9 instruments on the common calendar from 2018-02-12 to 2025-11-11 (scored from about Feb 2019). This is the same market the A048 study already looked at (different broker feed, wider universe), so it cannot add independent evidence; it can only contradict F.

## Mechanics
Identical to A048 (`docs/engineering/A048_PORTFOLIO_PROTOCOL.md`): decide at close, fill at next open, equal-risk volatility sizing to a 10% annual target (an equal share per instrument of the instruments present), 60-day volatility, gross cap 3x applied before the brake, 25% no-trade buffer, drawdown taper from 6% to flat at 10% with a 21-bar halt, USDJPY, USDCAD and USDCHF are quoted as quote-currency per USD, so they use the inverse return 1 - P0/P1. One change: financing is now DIRECTIONAL (long and short pay different swaps) and uses this broker's measured values.

## Costs (ECN account, assumptions stated)
One-way cost, share of notional = half an assumed spread + commission of 5 USD per lot per side (the broker's published ECN rate for majors and metals; whether it is per side or round-turn is not stated, so the dearer per-side reading is used). The ECN demo group quotes a spread of 0 in the data tool, so the spread is an ASSUMPTION of 1 bp full (0.5 bp one-way) for forex and 2 bp for gold:
EURUSD 1.0 bp, GBPUSD 1.0, USDJPY 1.0, USDCAD 1.0, USDCHF 1.0, AUDUSD 1.25, NZDUSD 1.5, XAUUSD 1.5, BTCUSD 8.0 (carried from A048; crypto commission is not published).
Financing per calendar day on notional, from the measured swap table of 2026-11-17 (bp per day; only debits are charged, credits are set to ZERO so that no result can rest on collecting today's interest differential):
| | long | short |
|---|---|---|
| EURUSD | 0.986 | 0 |
| GBPUSD | 0.140 | 0.216 |
| USDJPY | 0 | 1.910 |
| AUDUSD | 0 | 0.496 |
| USDCAD | 0 | 1.707 |
| USDCHF | 0 | 1.904 |
| NZDUSD | 0.909 | 0 |
| XAUUSD | 2.310 | 0 |
| BTCUSD | 6.849 | 6.849 |
Known weakness: swaps are today's snapshot applied to all years, and interest-rate gaps were very different in 2015-2021. The doubled-cost stress case (costs and financing x2) is a mark. A financing-free run is also printed for information only and plays no part in the verdict.

## Candidates (three, no others)
A: sign of the 252-day return. B: sign of close minus the 200-day average. C: average of the signs of the 63-, 126- and 252-day returns. Benchmark: the same sizing always long.

## Pass marks (verdict PASS only if ALL hold)
On F, for the best candidate (highest Sharpe on F):
1. Net return positive after base costs AND after doubled costs.
2. Deflated Sharpe probability >= 0.95; trials = 3 + 3 (A048) + 64 (A044) = 70, trial Sharpe variance from the three candidates.
3. Maximum drawdown <= 10% from the all-time high.
4. Positive profit on at least 5 of 8 instruments, none above 50% of total profit.
5. At least 100 position changes.
6. Beats the always-long basket on Sharpe.
On E, the same best candidate (not re-selected):
7. Net return positive after base AND doubled costs, and maximum drawdown <= 10% from the all-time high.
All six candidate-runs on both segments (twelve simulations) are logged in the registry as trials. A second run is blocked by the registry guard; any change needs a new written protocol and counts as new trials.

## What each outcome means
- FAIL: the rules are not shown to work on this universe; nothing goes to the locked holdout and the trend family is closed here. No tuning to make it pass.
- PASS: only then is the locked holdout used, once; the forward paper runner continues regardless as the clean out-of-sample evidence.

## Limits
F is short (about 2.8 scored years) so the test has little power: a FAIL means "not demonstrated", not "proven worthless", and a PASS would still be a simulation. Eight markets are correlated through the US dollar. Spreads are assumed, commission is the published rate, swaps are a snapshot. Returns-based simulation, not the order-level backtester.
