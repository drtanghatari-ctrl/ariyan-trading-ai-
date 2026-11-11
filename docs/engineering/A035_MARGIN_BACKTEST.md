# A035 — margin-aware offline backtest

Adds `backtest.py`, its tests and this document. It consumes an A007
`CandleDataset`, an A033 `MarginInstrumentSpec` and an A034 `Strategy`.
Offline research only: no ledger, authorization, Predictability Gate, broker or
live trading is touched, and results are not evidence of profitability.

## Execution model

- Decisions use fully closed bars. A decision at bar *i*'s close fills at bar
  *i+1*'s open. The last bar produces no decision because nothing can fill.
- One instrument, one position at a time, long or short, no pyramiding. A
  reversal closes and reopens at the same open.
- **Sizing:** lots are chosen so initial margin is about `margin_fraction` of
  balance, floored to the lot step and capped at the maximum lot. Below the
  minimum lot, or when margin plus commission exceeds balance, the entry is
  skipped and counted. A skipped target is retried at each later open while the
  signal persists.
- **Spread:** a full bid/ask spread in price units; each side pays half. Longs
  buy at open + half and are marked at close - half; shorts mirror this.
- **Commission:** per lot per side. **Financing:** per lot per bar held, signed
  (positive debits, negative credits), separate for long and short. This is a bar
  proxy, not a rollover-night swap model.
- **Stop-out:** each bar the adverse extreme (low for longs, high for shorts, plus
  half spread) is tested against maintenance margin. If equity is at or below it,
  the position is liquidated at that extreme, the bar's remaining path is not
  used, and re-entry in the same direction is blocked until the signal changes.
  A negative balance ends the run as `ruined`.
- **End of data:** open positions are liquidated at the last close with costs
  (`liquidate_at_end`, default true); set false to leave them marked.
- Shorting signals on instruments that declare shorting unavailable are treated
  as FLAT and counted.

## Output

`BacktestResult` holds provenance, metrics, trades and the equity curve.
`to_record()` gives plain JSON (curve optional) with explicit false
`investment_evidence` and `executable_support_established` flags. Provenance
includes dataset hash/labels, instrument fingerprint, strategy parameters and
config.

Metrics: final equity, total return, max drawdown (bar-close equity), trade
count, win rate, profit factor, average trade, per-bar Sharpe (and annualized
only when `periods_per_year` is supplied), exposure, spread/commission/financing
costs, stop-outs, skip counters and the ruin flag. All arithmetic runs in an
isolated Decimal context, independent of the caller's.

## Limits (do not read results as validated)

- All money is in the quote currency, treated as the account currency; no FX
  conversion. A real forex account needs a conversion layer.
- Intrabar order is unknown: stop-out uses the worst extreme, which is
  conservative, but entries at the open and no intrabar re-entry are assumptions.
- No slippage beyond spread, partial fills, liquidity, requotes, gaps over
  weekends, margin-call warnings, or broker-specific stop-out levels.
- Continuous, epoch-aligned bars only (A007 rule). Forex weeks, stock sessions and
  holidays need the session layer (A014/A015) wired in; do not backtest those
  markets through gaps.
- The spec and dataset are caller-asserted to describe the same instrument; only
  the spec's effective interval is checked. Real broker terms (contract size,
  margin, spread, swap) must be supplied from published specifications.
- Parameters chosen after viewing results bias findings. No out-of-sample or
  walk-forward procedure is provided here.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_backtest_a035 -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-one tests cover hand-computed long/short P/L, spread, commission and
financing, stop-out and ruin, no-lookahead and prefix invariance, sizing limits,
metrics, determinism under a hostile Decimal context, provenance records and
input validation.
