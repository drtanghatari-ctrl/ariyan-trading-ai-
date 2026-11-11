# A038 — walk-forward validation

Adds `walkforward.py` and tests. Offline research evidence only: it neither
authorizes trading nor proves a strategy works.

## Method

Each fold has a training window followed immediately by a test window.

1. Every candidate strategy runs a full A035 backtest on the **training window
   only**. The best by the chosen objective is selected. Candidates with fewer
   than `min_train_trades` training trades are ineligible; a fold with no eligible
   candidate stays flat and says so.
2. The chosen strategy runs on the **test window it has never seen**. The
   window is preceded by `lookback` warm-up bars so its first decision lands on the
   last bar before the test starts and the first fill is at the test's first open.
   Warm-up bars hold no position.
3. A buy-and-hold benchmark runs over the identical test window.

`rolling` folds slide the training window; `anchored=True` keeps the start fixed
so training grows. `step_bars` defaults to `test_bars` (non-overlapping test
windows). Objectives: `total_return_pct`, `sharpe_per_bar`, and
`return_over_drawdown` (return divided by max drawdown, or plain return when there
was no drawdown). Ties go to the earlier candidate.

`parameter_grid(factory, **lists)` builds the candidate set from every valid
combination, silently skipping combinations the strategy itself rejects.

Everything runs through `run_backtest`, so costs, margin, stop-outs, account
conversion (A036) and session gaps (A037) apply to both training and test.

## Output

Per fold: boundary timestamps, selected strategy and index, training objective
and return, test return, test drawdown, test trades, benchmark return, note.

Aggregate: compounded out-of-sample return, compounded benchmark return and the
difference, mean in-sample and out-of-sample returns and their gap
(`in_sample_minus_oos_pct`, a direct overfitting indicator), profitable-fold
share, worst fold return and drawdown, out-of-sample trade count, ruined folds,
`candidates_per_fold` and `distinct_selected_candidates` (selection stability).
Compounding clamps a fold at -100%. Folds are independent runs from the same
opening cash.

## How to read it

- A large positive in-sample-minus-OOS gap, an unstable selected candidate or
  few profitable folds all point to a strategy that fits history without
  predicting.
- Beating the benchmark over many folds and several instruments matters; one
  asset and one period does not.
- More candidates raise the chance that one wins by luck, so the count is reported.
- The range, candidate list and objective were chosen by a person who may have seen
  the data; true out-of-sample proof requires data collected after the decisions
  were fixed (forward paper trading).
- Sharpe is per bar, and warm-up bars slightly dilute test-window statistics.
- Folds with fewer than a few dozen trades are statistically thin.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_walkforward_a038 -v
```

Tests cover fold geometry, selection from training data only, detection of a
regime change, no look-ahead (changing later data or the test window cannot change
earlier selections), warm-up alignment, eligibility, manual compounding,
objectives, grids, validation errors, session and conversion pass-through and
determinism.
