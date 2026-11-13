# ARIYAN Trading AI — PROJECT STATE (source of truth for continuity)

Last updated: 2026-11-13 (after A041; broker now LiteFinance demo)

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

## Proposed next steps
1. (done) Forex/CFD instrument terms.
2. (done) Strategy interface + backtester.
2b. (done) FX conversion + sessions in backtests.
2c. (done) A038 walk-forward harness.
2d. (done) A039 execution + paper broker.
2e. (done) A040 MT5 demo adapter.
2g. NEXT (2026-11-13): (a) user runs `mt5_check` against LiteFinance demo with `--symbol-map EURUSD=EURUSD_o`; (b) user exports EURUSD history (MT5 History Center or a free download) and runs `fx_csv_check`; (c) real EURUSD backtest + walk-forward; (d) candle feed + forward demo loop only after (a) works and the user enables orders.
2f. (older, superseded by 2g) user runs `python -m ariyan_trading.mt5_check` on Windows with an Opofinance DEMO account (see A040 doc); then a candle-feed + scheduler loop for forward demo trading; multi-instrument portfolio risk; real historical data pipeline for forex/stocks.

## Open questions for the user
- Windows PC/VPS available? Opofinance demo account (login/server) created? Does Opofinance allow algorithmic trading / EAs on the account type?
- Which instruments first (e.g. EURUSD, XAUUSD, BTCUSD, a stock CFD)?
3. Decide the BUY-admission policy (what evidence unlocks entries).
4. Broker-agnostic execution interface + MT5 adapter (demo only) for Opofinance.

## Rules
- No real-money action without explicit human authorization.
- Keep this file updated at the end of every work session.
