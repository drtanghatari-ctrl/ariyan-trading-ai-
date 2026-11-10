# A049 rehearse STOP and FREEZE on paper orders

Pass `execution_state` to `execute_governed_paper_trade`.

| State | BUY | SELL |
| --- | --- | --- |
| `NORMAL` (default) | A027 denies new exposure | A006 checkpoint coordinator |
| `STOP` | Denied by the paper execution state | A006 checkpoint coordinator |
| `FREEZE` | Denied by the paper execution state | Denied by the paper execution state |

A state denial raises `PaperExecutionDenied` before the gate or checkpoint
coordinator is called. The exception carries the action and execution state.
An unsupported state raises `ValueError` before either path is reached.
A SELL allowed by STOP remains subject to the coordinator's checkpoint,
balance, and publication checks.

```sh
PYTHONPATH=app python -m ariyan_trading --governed --execution-state STOP
PYTHONPATH=app python -m ariyan_trading --governed --execution-state FREEZE
```

Both demos seed one synthetic unit before exercising the chosen state.
STOP exits it and reopens at checkpoint sequence two. FREEZE preserves
the unit and reopens at sequence one. Tests also check that blocked
requests cause zero SQL statements and leave the anchor bytes intact.

This is a caller-supplied state for an offline paper order. Existing calls
without a state use NORMAL. A049 does not store or authenticate the state
or coordinate a transition with an order already in progress. The demo
uses a disposable ledger and no exchange connection.
