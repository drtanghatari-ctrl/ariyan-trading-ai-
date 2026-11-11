# ARIYAN Trading AI — PROJECT STATE (source of truth for continuity)

Last updated: 2026-11-11

## Where the code lives
- Repo: https://github.com/drtanghatari-ctrl/ariyan-trading-ai-
- Active branch: `development/accelerated-build` (real application; `main` only holds a reference ZIP + README)
- Reference archive on `main`: `ARIYAN_TRADING_AI_CONSOLIDATED_MASTER_2026-10-17.zip` (handoff/test reference only; says full project NOT finished, 14 blockers)
- Push access from Claude: NOT yet available (install the Claude GitHub App on the repo / reconnect GitHub in claude.ai settings)

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
1. No FOREX asset class and no CFD product type in A012.
2. Strategy is a toy 3/5 SMA crossover (engine.py); no real strategy framework or backtester metrics.
3. BUY is always denied by design (A027 has no positive admission path) — needs an explicit governance decision to allow validated entries.
4. Replay is single-symbol, long-only, spot-style; no shorting, leverage, margin, multi-instrument portfolio risk.
5. No broker adapter (MT5/Opofinance), no live/demo connectivity.
6. Native Windows checkpoint durability not done; MT5 Python package needs Windows + terminal.

## Proposed next steps
1. Add FOREX asset class + CFD product type + lot/pip/margin semantics (new instrument spec version).
2. Strategy interface + backtest metrics (return, drawdown, Sharpe, costs/spread).
3. Decide the BUY-admission policy (what evidence unlocks entries).
4. Broker-agnostic execution interface + MT5 adapter (demo only) for Opofinance.

## Rules
- No real-money action without explicit human authorization.
- Keep this file updated at the end of every work session.
