# A046 Forecast-driven signals (Kronos, TimesFM, any model)

Models run outside this code and write a forecast CSV; this code validates it, turns it into a `ForecastSignal` strategy, and scores forecast quality. Research and paper only.

## File format
`decision_ts_ms,symbol,horizon_bars,last_close,q10,q50,q90,model,model_version,context_end_ms`
One row per decision bar. q10/q50/q90 are forecast prices. `context_end_ms` must equal `decision_ts_ms` (the model saw nothing later). `last_close` must match the dataset's close or the signal is FLAT. Duplicates, bad numbers and quantile disorder are rejected.

## Signal rule
edge = ln(q50/close), noise = ln(q90/q10)/2.563. LONG if edge > cost + margin*noise, SHORT if edge < -(cost + margin*noise), else FLAT (the no-trade region of the handoff spec). Missing forecast, wrong model name or data mismatch means FLAT.

## Quality checks (`evaluate_forecasts`)
Directional accuracy, rank IC, error against a zero forecast, and q10-q90 coverage (target 0.8, i.e. calibration). Use on development data only.

## Running a model (laptop)
`research/make_forecasts.py DATA.csv SYMBOL OUT.csv --model naive|kronos|timesfm --end 2025-11-11 [--start ...] [--limit 3]`
The naive baseline (trailing-volatility interval around "no change") is tested; on EURUSD development data its coverage is 81.6%. The Kronos and TimesFM adapters follow the projects' README examples but are UNTESTED: smoke-test with `--limit 3` first. Kronos: clone github.com/shiyu-coder/Kronos, install its requirements, pass `--kronos-repo`. TimesFM 3.0 weights are non-commercial; check the license before any real-money use.

## Limits
- Both models were pretrained on market data that very likely covers our history, so a backtest of them is optimistic by construction. Forward paper trading is the only clean test.
- A forecaster must beat the naive baseline AND simple trend rules after costs, out of sample, to be kept (handoff spec section 4.5). Every run is logged in the experiment registry.
