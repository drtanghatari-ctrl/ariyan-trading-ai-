# ARIYAN Trading AI — PROJECT STATE (source of truth for continuity)

Last updated: 2026-11-13 (after A045)

## Where the code lives
- Repo: https://github.com/drtanghatari-ctrl/ariyan-trading-ai-
- Active branch: `development/accelerated-build` (real application; `main` only holds a reference ZIP + README)
- Reference archive on `main`: `ARIYAN_TRADING_AI_CONSOLIDATED_MASTER_2026-10-17.zip` (handoff/test reference only; says full project NOT finished, 14 blockers)
- Push access from Claude: WORKING (Claude GitHub App installed 2026-11-11; push to development/accelerated-build confirmed)

## Goal (user direction)
Trading AI that works across crypto, stocks, forex (plus gold/silver/oil per MULTI_ASSET_SCOPE.md).
Broker: Opofinance (https://opofinance.com/) — offers MT4/MT5, cTrader, TradingView; forex, metals, commodities, stocks, indices, crypto (likely CFDs). API/EA support NOT confirmed on their site — verify with broker.
Order of work: paper trading + backtesting -> demo account -> live only after validation and explicit human authorization.

## Baseline (verified 2026-11-11)
- Python 3.13, `cryptography`; run: `PYTHONPATH=app python -m unittest discover -s tests`
- 1249 tests pass (1 expected failure). ~11k LOC app, ~19k LOC tests, docs A006–A029 in docs/engineering/
- Demo: `PYTHONPATH=app python -m ariyan_trading --governed`

## What exists
Paper ledger with authenticated checkpoints, OHLCV replay (A007), dataset plan (A009), Binance archive intake (A010),
instrument definitions (A012: crypto/equity/fund/metal/energy; SPOT/SHARE/FUND_SHARE/FUTURE), session schedules (A014),
cash trade math (A016), replay batch/view/export/review (A021–A026), Predictability Gate (A027), governed paper entry (A028/A029).

## Known gaps vs goal
1. DONE (metadata only): forex + CFD terms in A033 (`margin_instruments.py`). Still missing: margin-aware accounting, replay and risk for these products.
2. DONE (offline): strategy interface A034 + margin-aware backtester A035 with costs, stop-out and metrics. Still missing: FX/account-currency conversion, session calendars wired into backtest, walk-forward/out-of-sample validation, real broker cost data, realistic strategies.
3. BUY is always denied by the ORIGINAL governed paper path (A027 has no positive admission path). The new A035-A040 stack does not use A027; it is a separate research/execution track guarded by A039 limits. Decide whether/how A027-style evidence should gate it.
4. A007 replay stays single-symbol/long-only/spot-style (untouched). A035 adds long/short margin backtesting for ONE instrument; no multi-instrument portfolio risk yet.
5. DONE (untested against a real terminal): MT5 demo adapter A040. Live trading remains unsupported by design.
6. Native Windows checkpoint durability not done; MT5 Python package needs Windows + terminal.

## Progress log
- Step 1 DONE: A033 forex/CFD instrument terms (lot, pip, margin rate, shorting, exact notional/margin/P&L in quote currency). 17 new tests. A012 untouched.

- Step 2 DONE: A034 `strategies.py` (stateless Strategy, SmaCross, Momentum, BuyAndHold) and A035 `backtest.py` (next-open fills, spread, commission, financing, margin sizing, stop-out, ruin, metrics). 30 new tests. Smoke-run on real BTCUSDT sample OK (24 bars; plumbing only).

- A036 DONE: account-currency conversion (multi-leg chains, direct/inverted, pessimistic stop-out rates). A037 DONE: session-aware datasets (validated closures), DST-aware daily/weekly schedule builders, elapsed-time financing, gap-through-stop-out. 30 new tests (1326 total).

- A038 DONE: walk-forward validation harness (`walkforward.py`): train-only selection, unseen test windows with warm-up, benchmark, in-sample vs OOS gap, parameter grids. 12 new tests.

- A039 DONE: broker-neutral execution (`execution.py`): Broker interface, PaperBroker (margin, SL/TP gaps, stop-out, idempotent orders), GuardedBroker (risk limits, kill switch, fail-closed, LIVE refused), SignalExecutor. 27 new tests.

- A040 DONE: MT5 demo-only adapter (`mt5_adapter.py`, `mt5_check.py`): refuses REAL/CONTEST accounts (checked on every action), no stored secrets, own-magic positions only, unknown outcomes fail closed. 18 new tests against a FAKE terminal only (never run against real MT5).

- 2026-11-12: user installed MT5 on a Windows laptop and logged in to Opofinance demo (Opogroup-Server1, USD, **Netting**). Adapter updated: netting/exchange/unknown accounts refuse orders on a symbol that already has a position; `mt5_check` reports margin mode. 5 new tests. Real connection check NOT yet run; charts/Market Watch were empty (no data) at last report.

- 2026-11-13: BROKER CHANGED. Opofinance demo never connected (laptop network/auth problems, hours lost). User opened a LiteFinance demo: login 91565990, server `LiteFinance-MT5-Demo`, **Hedge** account, symbols carry suffix `_o` (e.g. `EURUSD_o`). MT5 terminal now connects (AWS Frankfurt, ~112 ms) and shows real EURUSD candles. Journal says "trading has been disabled - disabled on server": probably logged in with the INVESTOR (read-only) password; orders would fail until the trading password is used. Algo Trading button was off. `mt5_check` gained `--symbol-map EURUSD=EURUSD_o`. The real connection check has NOT been run yet.
- A041 DONE: offline FX/CSV importer (`fx_csv.py`, `fx_csv_check.py`): Stooq/Yahoo/Dukascopy/MT5/canonical headers, explicit timezone, drops out-of-session bars, keeps longest gap-free run, never repairs. 8 new tests (1396 total). Tested on synthetic files only. The cloud workspace cannot download market data (shell proxy blocks data sites; web-fetch summarises and is unreliable), so real data must be downloaded on the user's laptop (or exported from MT5 History Center) and sent here.

- 2026-11-13 10:17 Tehran: FIRST REAL `mt5_check` PASSED (photo from user). Account: MetaQuotes-Demo, login 115560232 (user opened MetaQuotes' default demo after LiteFinance's demo logged in read-only), Hedge, currency EUR, balance 100000, mode DEMO, 0 positions, EURUSD quote bid 1.10576 / ask 1.10577, symbol name plain `EURUSD`. Trading enabled on this account. The adapter's refusal of non-trading accounts worked as designed on LiteFinance investor login. Caveat: MetaQuotes-Demo is a generic feed; its spreads/execution do not represent any real broker's costs. No orders have ever been sent.

- A042 DONE: forward PAPER runner on real MT5 data (`forward.py`, `forward_demo.py`; adapter gained read-only `closed_candles`, `symbol_terms`, `timeframe_seconds`; `SignalExecutor.warm_up`). Sends NO orders to MT5; trades the A039 PaperBroker with real quotes, JSONL log. 7 new tests (1403 total) against a FAKE terminal; NOT yet run against the real terminal. Enabling real demo orders remains a separate explicit decision by the user.

- 2026-11-13 10:49 Tehran: A042 `forward_demo --max-steps 1` RAN CLEANLY on the real MetaQuotes-Demo terminal (paper_only true, orders_sent_to_mt5 0). User also exported EURUSD D1 history from MT5: 2079 bars (2018-11-13 to 2026-11-13); file not yet received here. User gets code via ZIP sent in chat (ariyan_A042_new.zip), not GitHub.

- 2026-11-13 11:28 Tehran: user's continuous `forward_demo` run crashed on the real terminal with "Too many decimal places" (float noise in MT5 quote). FIXED: `_dec` in mt5_adapter now rounds floats to 8 places; regression test added.
- A043 DONE: `strategies_extra.py` (TrendFilter, DonchianBreakout, RsiReversion, BollingerReversion, Ensemble) + `A043_STRATEGY_CATALOG.md` with evidence and sources (AQR Trends Everywhere, BIS WP366, Quantopian overfitting study). `forward_demo --strategy` accepts trend:/donchian:/rsi/boll and `+` ensembles. 1420 tests pass. No profitability claim; judge via walk-forward on real data (EURUSD D1 export of 2079 bars still not received here).

- 2026-11-13 14:50 Tehran: REAL DATA RECEIVED (EURUSD D1, 2079 rows, MT5 export). Importer: broker publishes no bars on Dec 25/Jan 1, so `load_fx_csv` now declares them closed for daily data (`holidays` param); result = one gap-free run of 2076 bars. A044 study (`research/eurusd_d1_study.py`, params fixed before results; results JSON + `A044_EURUSD_D1_RESULTS.md`): NO reliable edge on EURUSD daily. Best fixed strategies ~+12% over 8y with ~18% drawdown (Sharpe ~0.3), mostly negative under a swap stress; walk-forward OOS +2.6% vs buy&hold +1.1% over ~5y, 4/10 profitable folds, IS-OOS gap 6.7 pts, 20 OOS trades. Conclusion: single-pair textbook rules are not shown profitable; next is multi-instrument data (XAUUSD, GBPUSD, USDJPY, indices, BTCUSD) and a portfolio layer, plus real cost data.

- A045 DONE: research controls (`research_controls.py`, `scorecard.py`, `docs/engineering/RESEARCH_PROTOCOL.md`). User decisions: max drawdown 10%, Daily timeframe, last-12-months locked final test. Hash-chained registry, once-only holdout, scorecard with bootstrap CIs, probabilistic/deflated Sharpe. EURUSD holdout recorded as contaminated (registry in `research/registry/`). 1436 tests pass. User sent M1 files (3.5 months) for XAUUSD, GBPUSD, USDJPY, US500; still need DAILY exports for those plus BTCUSD.

- 2026-11-13 20:40 Tehran: Daily exports received for GBPUSD, USDJPY, XAUUSD (clean, 2036 bars each after declared holidays, 2018-11-13..2026-11-12) and US500 (BROKEN: broker has no bars 2025-07-16..2025-09-09, re-export identical; excluded for now). BTCUSD still missing. Holdouts (last 12 months, from 2025-11-12, 254 bars) locked and recorded in `research/registry/experiments.jsonl` for EURUSD (already contaminated), GBPUSD, USDJPY, XAUUSD; no strategy has been run on the new three. Loader: `research/load_d1.py`; `research/lock_holdouts.py`.

## Proposed next steps
1. (done) Forex/CFD instrument terms.
2. (done) Strategy interface + backtester.
2b. (done) FX conversion + sessions in backtests.
2c. (done) A038 walk-forward harness.
2d. (done) A039 execution + paper broker.
2e. (done) A040 MT5 demo adapter.
2i. NEXT (after A044): user exports D1 history for more instruments (XAUUSD, GBPUSD, USDJPY, a stock index, BTCUSD) and keeps the forward paper runner going; I build a multi-instrument portfolio backtest (volatility-scaled positions) and re-test trend/momentum as a diversified portfolio.
2h. (older) (after A042): user downloads the new ZIP, runs `forward_demo --max-steps 1` on the real terminal, then leaves it running; user exports EURUSD D1 history for `fx_csv_check`; then real backtest + walk-forward; hourly import needs a server-time (NY+7 / DST) rule.
2g. (older) (2026-11-13): (a) user runs `mt5_check` against LiteFinance demo with `--symbol-map EURUSD=EURUSD_o`; (b) user exports EURUSD history (MT5 History Center or a free download) and runs `fx_csv_check`; (c) real EURUSD backtest + walk-forward; (d) candle feed + forward demo loop only after (a) works and the user enables orders.
2f. (older, superseded by 2g) user runs `python -m ariyan_trading.mt5_check` on Windows with an Opofinance DEMO account (see A040 doc); then a candle-feed + scheduler loop for forward demo trading; multi-instrument portfolio risk; real historical data pipeline for forex/stocks.

## Open questions for the user
- Windows PC/VPS available? Opofinance demo account (login/server) created? Does Opofinance allow algorithmic trading / EAs on the account type?
- Which instruments first (e.g. EURUSD, XAUUSD, BTCUSD, a stock CFD)?
3. Decide the BUY-admission policy (what evidence unlocks entries).
4. Broker-agnostic execution interface + MT5 adapter (demo only) for Opofinance.

## Rules
- No real-money action without explicit human authorization.
- Keep this file updated at the end of every work session.
