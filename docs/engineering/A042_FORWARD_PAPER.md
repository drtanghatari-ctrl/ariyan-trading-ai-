# A042 — Forward paper trading on real MT5 data (no orders sent)

`forward.py` (`ForwardPaperRunner`) and `forward_demo.py` (CLI) watch real closed candles from an MT5
demo terminal and trade a **simulated** account with them. The terminal is used read-only: closed
candles, quotes and contract terms. Nothing is ever sent to MT5 (`orders_sent_to_mt5: 0`, and a test
asserts the fake terminal received no order).

## How it works

1. Connects with `MT5DemoBroker` (demo-only, refuses real accounts, no stored password).
2. Reads contract terms from the terminal and builds a paper EURUSD-style instrument (A033) with a
   USD paper account (default 10,000) and the PaperBroker (A039).
3. First poll: loads recent closed candles as history only (`SignalExecutor.warm_up`), takes no trade.
4. Each later poll: for every newly closed candle, `SignalExecutor` -> `GuardedBroker` -> `PaperBroker`
   decide and fill at the current quote (ask for buys, bid for sells, spread included).
5. Appends JSON lines to the log: START, CANDLE (OHLC, quote, actions, paper equity), ERROR, STOPPED.
6. Five consecutive terminal errors stop the run.

## Run (Windows, MT5 open and logged in to a DEMO account)

```
set MT5_PASSWORD=your-demo-password
set PYTHONPATH=app
cls
python -m ariyan_trading.forward_demo --login 115560232 --server MetaQuotes-Demo --symbol EURUSD --timeframe H1 --strategy sma:10:30 --lots 0.01 --log forward_log.jsonl
```

Use `--max-steps 1` for a single dry check. Add `--broker-symbol EURUSD_o` when your broker adds a
suffix. Strategies: `hold`, `sma:SHORT:LONG[:short]`, `momentum:BARS[:short]`. Shorting is off unless
`:short` is appended. Stop with Ctrl+C. Keep the laptop awake and MT5 running while it runs.

## Limits

- USD-quoted six-letter forex pairs only; paper account is in USD.
- Fills use the quote at the moment the loop sees the closed candle; real fills can differ (slippage,
  requotes, latency). Swap and commission are not modelled.
- Paper state is in memory; a restart starts a fresh run.
- Candle times are broker server time, not true UTC.
- A few weeks of paper trading on one pair says almost nothing about profitability. It tests the
  plumbing and shows realistic spreads and timing.
- A generic demo server (MetaQuotes-Demo) does not represent any real broker's costs.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_forward_a042 -v
```
