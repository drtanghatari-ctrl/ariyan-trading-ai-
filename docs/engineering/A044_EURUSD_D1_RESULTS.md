# A044 — EURUSD daily study (real MT5 export, 2018-11-13 to 2026-11-12)

Script: `research/eurusd_d1_study.py` (parameters fixed before any result was seen). Raw numbers:
`research/results/eurusd_d1_2026-11-13.json`. Data: 2,076 daily bars from a MetaQuotes-Demo MT5 export
(sha256 b91fd22f...), one gap-free run after declaring Dec 25 / Jan 1 closed. 2 bars fell on declared holidays and were dropped.

Setup: USD account 10,000, about 1x notional exposure, 1.0-pip spread, no commission. Swap is unknown, so two
scenarios: none, and a punishing 6 USD per lot per calendar day charged in BOTH directions (real swap depends on
direction and on interest-rate differences, so this stress is pessimistic). Returns below are totals over ~8 years.

## Fixed-parameter strategies (14, untuned)

| Strategy | No swap: return / max drawdown | Swap stress: return |
|---|---|---|
| Buy and hold | -1.9% / 20.2% | -15.9% |
| Momentum 126 long/short | +12.5% / 18.6% | -0.8% |
| Bollinger 20,2 long/short | +11.8% / 7.6% | +2.9% |
| Trend 200 long/short | +7.6% / 17.4% | -5.0% |
| Ensemble trend+Donchian+momentum | +7.1% / 16.5% | -5.0% |
| Bollinger long only | +7.4% / 6.8% | +2.7% |
| Donchian 55/20 long/short | -5.4% / 12.1% | -13.5% |
| SMA 50/200 long/short | -5.4% / 28.7% | -18.0% |
| RSI(2) reversion (either) | -3% to -5% | -5.6% to -6.0% |

Best annualised Sharpe in the table is about 0.3. With 14 strategies tested, one or two looking mildly positive is what
chance alone produces.

## Walk-forward (train 756 bars, test 126, rolling, 10 folds, objective Sharpe; ~5 years out of sample)

| Candidate set | Out-of-sample | Buy and hold | In-sample minus OOS | Profitable folds | OOS trades |
|---|---|---|---|---|---|
| All 50 candidates | +2.6% | +1.1% | 6.7 pts | 4/10 | 20 |
| Donchian only (16) | +6.6% | +1.1% | 3.6 pts | 5/10 | 17 |
| RSI reversion (6) | +2.8% | +1.1% | 2.3 pts | 4/10 | 31 |
| SMA cross (18) | +1.9% | +1.1% | 8.0 pts | 3/10 | 25 |
| Trend filter (10) | -1.1% | +1.1% | 10.4 pts | 3/10 | 56 |

Under the swap stress the picture is the same or worse (all-candidates -0.2% against a -8.0% benchmark).

## Reading

- No strategy shows a reliable edge on EURUSD daily after costs. Profit appears only in some folds (3 to 5 of 10),
  in-sample results beat out-of-sample ones by several points, and out-of-sample trade counts (17 to 56) are far too
  few to separate skill from luck.
- "Donchian only" has the best walk-forward number, but it is the best of five looks, from 17 trades.
- This matches the literature: trend following is documented as a diversified, many-market portfolio effect,
  not a single-pair one.
- Not tested: other instruments, intraday bars, direction-specific swap, real spreads (demo spreads are not a real
  broker's), position sizing by volatility, and multi-instrument portfolios.
