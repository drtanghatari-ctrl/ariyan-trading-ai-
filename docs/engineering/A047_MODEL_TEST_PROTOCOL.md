# A047 Pre-registered test of forecasting models (Kronos-small, TimesFM)

Written 2026-11-17 BEFORE any result beyond the single EURUSD Kronos run. Purpose: settle once whether these models are useful as signals for the strategist, instead of arguing from one pair.

## Fixed design
- Instruments: EURUSD, GBPUSD, USDJPY, XAUUSD, BTCUSD (US500 has a broker data hole).
- Models: kronos-small (NeoQuasar, 5 sampled paths, median/q10/q90) and timesfm-3.0 (deciles of log price). Each one setting only.
- Decisions: daily closes 2023-01-01 to 2025-11-11 (development period only; the locked last 12 months are NOT forecast).
- Context 400 bars, horizon 1 bar, no tuning, no re-running with other settings.

## Pass marks (all four required, applied by `forecast_study.study`)
1. Mean rank IC across instruments >= 0.03, its 90% block-bootstrap interval above 0, and positive on >= 60% of instruments.
2. Pooled directional accuracy >= 52%.
3. Error lower than a "no change" forecast on >= 60% of instruments.
4. Pooled 10-90% interval coverage between 70% and 90%.

## Consequences
- FAIL on any mark: the model is dropped from the strategist. A retry needs a new written protocol and counts as new trials in the registry.
- PASS: the model goes on to the next stage only: a trading test in the portfolio engine, compared with the plain trend baseline (ablation), under stressed costs, with the 10% drawdown limit, then forward paper trading. Passing forecast quality alone is not a reason to trade.

## Known limits
Both models were pretrained on data that very likely includes this period, so a PASS is optimistic. A FAIL is therefore strong evidence against; a PASS is only permission to test further.
Already seen (before this protocol): Kronos-small on EURUSD alone, direction 47.2%, rank IC -0.018, coverage 57.7%.
