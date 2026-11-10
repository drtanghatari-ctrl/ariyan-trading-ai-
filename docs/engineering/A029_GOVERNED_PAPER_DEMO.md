# A029 governed paper demo

Run the A028 boundary through the ATAI command line:

```sh
PYTHONPATH=app python -m ariyan_trading --governed
```

The command creates a disposable ledger with 10,000.00 in paper cash. A
synthetic fixture trade seeds one unit at 100.00 to exercise an exit. A
subsequent BUY through the governed boundary returns `NO_TRADE` with
`MISSING_VALIDATION_EVIDENCE`. A SELL through the same boundary exits the
fixture position at 101.00. The authenticated reopen verifies cash of 10,001.00,
zero units, and a checkpoint sequence of two.

The fixture runs in a temporary directory with an ephemeral key. The
command accepts no user-ledger path or broker configuration. The displayed
balances illustrate the synthetic lifecycle and provide no performance
evidence. Native Windows checkpoint durability and the legacy enrollment gap
remain separate work.

Use `PYTHONPATH=app python -m ariyan_trading` to run the original A006
coordinator demo.
