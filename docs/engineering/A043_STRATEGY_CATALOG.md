# A043 — Strategy catalog (what was added, and what the evidence does and does not say)

`strategies_extra.py` adds five rule-based strategies and an ensemble to the A034 set (BuyAndHold,
SmaCross, Momentum). All share the A034 contract (decision at a closed candle, deterministic, window
only), so the backtester, walk-forward harness and the forward paper runner use them unchanged.

| Strategy | Idea | Defaults | Needs |
|---|---|---|---|
| `TrendFilter` | close vs simple moving average | window 200 | trending markets |
| `DonchianBreakout` | Turtle-style channel breakout, exit on a shorter channel | entry 20, exit 10 | trending markets |
| `RsiReversion` | Connors-style RSI(2) dip-buy inside an uptrend, exit on a short average | RSI 2 < 10, exit 5, trend 200 | ranging/pullback markets |
| `BollingerReversion` | fade closes beyond k standard deviations, exit at the mean | window 20, k 2 | ranging markets |
| `Ensemble` | majority or unanimous vote of other strategies | majority | diversity among members |

Shorts are off unless `allow_short=True` (`:short` in the command line).

## What the research found (and the limits)

- **Trend following / time-series momentum** has the strongest published support. AQR's "Trends
  Everywhere" reports it worked out of sample across 82 securities not studied before, in many asset
  classes and at several horizons. That evidence is for diversified portfolios across many markets, not
  one currency pair, and past performance does not guarantee future results.
- **Currency momentum** (BIS Working Paper 366) found a cross-sectional spread of up to 10% a year,
  partly absorbed by transaction costs. It ranks many currencies against each other, so it cannot be
  tested on a single pair; it needs the multi-instrument portfolio work still on the roadmap.
- **Backtests mislead.** A Quantopian study of 888 algorithms found backtest Sharpe ratio explained
  under 2.5% of out-of-sample Sharpe (R² < 0.025), and the more backtests a developer ran, the larger
  the gap between in-sample and out-of-sample results.
- **Short-horizon mean reversion and breakout rules** are popular and well documented in books and
  open-source repositories, but I found no reliable evidence that a default parameter set is profitable
  on one retail currency pair after spread and swap.

No strategy is claimed to be profitable. "Most profitable" is not a property a rule has in advance.

## How to judge them here

1. Backtest on real data with real costs (A035 spread, commission, financing).
2. Use walk-forward validation (A038): choose parameters on past windows only and score on windows the
   choice never saw. Compare to BuyAndHold. Distrust any result that only appears in-sample.
3. Count how many variants you try; each one raises the odds of fooling yourself.
4. Forward paper test (A042) before anything touches a demo account with orders.

## Sources

- Quantopian study summary: https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/
- AQR, Trends Everywhere: https://www.aqr.com/Insights/Research/Journal-Article/Trends-Everywhere
- BIS Working Paper 366, Currency Momentum Strategies: https://www.bis.org/publ/work366.pdf
- Search hits not read in full: https://quantpedia.com/time-series-momentum-works-everywhere/ ,
  https://quantpedia.com/?p=33415

I did not browse GitHub repositories one by one; a repository's published return numbers are not
evidence, so none were copied. The rules above are standard textbook definitions written from scratch.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_strategies_extra_a043 -v
```
