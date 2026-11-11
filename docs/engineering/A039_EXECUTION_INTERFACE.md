# A039 — broker-neutral execution, paper broker and risk guard

Adds `execution.py` and tests. No real venue is contacted. A LIVE-mode broker is
refused outright: this version has no path to real-money trading, and the
repository rule (no real-money action without explicit human authorization) is
unchanged.

## Pieces

- **Types:** `OrderRequest` (market order, optional stop-loss/take-profit, a
  required idempotency token `client_order_id`), `OrderResult` (`FILLED`,
  `REJECTED` or `UNKNOWN`), `Quote`, `Position`, `AccountState`, `BrokerMode`
  (`PAPER`, `DEMO`, `LIVE`).
- **`Broker` interface:** `mode`, `account()`, `positions()`, `quote()`,
  `submit()`, `close_position()`. Every implementation must make orders idempotent
  per client order ID. The MT5 demo adapter (A040) implements the same interface.
- **`PaperBroker`:** a hedging account simulated from quotes the caller supplies.
  BUYs fill at the ask, SELLs at the bid (the spread is paid, not modeled
  separately). Margin, maintenance margin, lot limits and price grids come from
  A033 instrument terms; commission is per lot per side. Stop-loss and take-profit
  are checked on each new quote and **gap through at the new quote** (a gap can fill
  worse than the stop). Positions close in worst-first order when equity falls to
  maintenance margin (stop-out). Quote-currency amounts convert through caller
  `rates`. It keeps a journal of every result.
- **`GuardedBroker`:** wraps any broker with hard limits (allowed symbols, lots
  per order, open positions, total lots, margin fraction of equity, daily loss
  fraction, mandatory stop-loss) and a kill switch. It fails closed:
  - a LIVE broker is refused at construction, and a mode flip halts trading;
  - a broker exception during `submit` yields `UNKNOWN`, halts trading, and the
    same ID is never resubmitted until a human reconciles;
  - unreadable account state halts trading;
  - exceeding the daily-loss baseline halts trading;
  - a fill that breaches the margin-fraction limit is immediately closed
    ("undone") and reported as rejected;
  - closing positions and `flatten()` are always allowed, even when halted;
  - `resume()` is an explicit human action that clears a halt and resets the baseline.
- **`SignalExecutor`:** maps a Strategy's target (LONG/SHORT/FLAT) to orders on one
  symbol with fixed lots, optionally attaching a stop at a fixed distance. Order IDs
  are deterministic (`RUN-O000001`, `RUN-C000002`, ...), so a restarted process
  replaying candles cannot double-submit; one position per symbol is enforced.

## Limits

- Market orders only; no pending/limit orders, partial fills, slippage beyond the
  quote spread, requotes, trading sessions or margin-call warnings.
- The paper broker is a simulation. Passing here says nothing about how a real
  broker's fills, rejections or latencies behave.
- The guard's undo of a margin-breaching fill costs the spread; the pre-trade check
  is only as good as the broker's reported margin.
- Daily baseline is set at construction and by `start_new_day()`; the caller
  schedules resets. No wall-clock logic exists here.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_execution_a039 -v
```
