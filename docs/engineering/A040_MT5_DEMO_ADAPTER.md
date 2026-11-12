# A040 — MetaTrader 5 demo-only adapter (Opofinance-ready)

Adds `mt5_adapter.py` (`MT5DemoBroker`), `mt5_check.py` and tests. It implements the
A039 `Broker` interface over the official `MetaTrader5` Python module, so
`GuardedBroker` and `SignalExecutor` work unchanged. It has been tested only
against a **fake terminal**; it has never run against a real MetaTrader 5
installation or any broker server. Treat the first real run as an integration
test, on a demo account.

## Safety design

- **Demo only.** `connect` verifies `account_info().trade_mode` is DEMO and refuses
  REAL and CONTEST accounts. The check is repeated before every read and every
  order, so a terminal that gets switched to a real account is detected and refused.
  Optionally `expected_server` pins the broker server name.
- **No stored secrets.** The password is passed to `connect` once and never kept,
  logged or returned. The check tool reads it from `MT5_PASSWORD` or a hidden prompt,
  never from the command line.
- **Own positions only.** All orders carry this system's `magic` number; positions
  with another magic (manual trades, other robots) are invisible and cannot be closed.
- **Fail closed on uncertainty.** `order_send` returning nothing, a timeout or any
  ambiguous return code raises `MT5Error` (outcome unknown). `GuardedBroker` converts
  that into `UNKNOWN` and halts trading until a human reconciles. Only unambiguous
  refusals (no money, market closed, invalid volume and similar) become `REJECTED`.
- **Idempotency.** The client order ID is sent as the MT5 order comment (at most 31
  characters). A repeat in the same process returns the first result; after a
  restart, an open position carrying that comment is reported as already filled.
  A position that already closed cannot be recognized this way.

## What you need (Windows)

MT5's Python package works only on Windows with the desktop terminal installed.

1. A Windows PC or VPS (a Linux host cannot run this adapter).
2. The MetaTrader 5 terminal from your broker (for Opofinance, their website lists MT5
   downloads). Log in once manually, and in Tools > Options > Expert Advisors tick
   **Allow algorithmic trading**.
3. A **demo** account: its login number, password and exact server name (the broker
   sends these; copy the server string exactly). I could not confirm from the broker's
   public site whether it offers demo accounts or algorithmic trading, so check
   with them first.
4. Python 3.11+ and `pip install MetaTrader5 cryptography`.
5. This repository: `git clone` and use the `development/accelerated-build` branch.

## First run: read-only connection check

```
set MT5_PASSWORD=your-demo-password
set PYTHONPATH=app
python -m ariyan_trading.mt5_check --login 12345678 --server Exact-Demo-Server --symbol EURUSD
```

Expected: JSON with `"connected": true`, `"mode": "DEMO"`, your balance and a quote.
It places no orders. If it prints `not a DEMO account`, stop: you are logged in to a
real account. Some brokers add a suffix to symbols (for example `EURUSD.r` or
`EURUSDm`); pass the mapping as `symbol_map={'EURUSD': 'EURUSDm'}`.

## Using it in code (demo)

```python
from decimal import Decimal
from ariyan_trading.execution import GuardedBroker, RiskLimits, SignalExecutor
from ariyan_trading.mt5_adapter import MT5DemoBroker, load_mt5
from ariyan_trading.strategies import SmaCross

broker = MT5DemoBroker(load_mt5(), magic=7700001, symbol_map={'EURUSD': 'EURUSD'},
                       expected_server='Exact-Demo-Server')
broker.connect(login, password, 'Exact-Demo-Server')
guard = GuardedBroker(broker, RiskLimits(
    allowed_symbols=frozenset({'EURUSD'}), max_lots_per_order=Decimal('0.10'),
    max_open_positions=1, max_total_lots=Decimal('0.10'), max_margin_fraction=Decimal('0.2'),
    max_daily_loss_fraction=Decimal('0.02'), require_stop_loss=True))
executor = SignalExecutor(guard, SmaCross(10, 30), 'EURUSD', '0.01', 'DEMO-RUN-1',
                          stop_distance='0.00500')
# After each fully closed candle: executor.on_candle(candle)
```

No scheduler, candle feed or loop is included; wiring one is the next piece of
work. Keep every limit tight on a demo account too: the goal is to learn how the
broker really behaves (fills, rejections, spreads, swaps).

## Limits

- Market orders only; no pending orders, partial-fill handling or modification of
  stops after entry.
- Unrealized P&L is MT5's `profit` field (excludes swap and commission).
- Account-currency conversion is done by MT5 itself; the adapter just reports it.
- **Account type.** The terminal reports hedging, netting or exchange margin mode
  (`account_type()`, also shown by `mt5_check`). On a hedging account each order is its
  own position. On a **netting or exchange account, or when the mode is unknown**, orders
  on a symbol merge into one position, so the adapter refuses any new order while the
  symbol already has a position (ours or manual), reporting
  `NETTING_SYMBOL_ALREADY_HAS_POSITION`. Close first with `close_position`, then
  submit; `SignalExecutor` already works in that order. Opofinance's demo account was
  seen reporting **Netting**. Netting behavior is tested against the fake terminal only.
- Real broker behavior (requotes, slippage, minimum stop distance, trading hours,
  execution delays) is unverified.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_mt5_adapter_a040 -v
```
