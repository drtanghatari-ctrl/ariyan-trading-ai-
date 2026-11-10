# A028 offline paper-entry boundary

New offline paper-order callers can use
`ariyan_trading.paper_entry.execute_governed_paper_trade` with the same order
arguments as `execute_checkpointed_trade` and an optional
`review_directory` for BUY evidence.

- **BUY** calls the A027 Predictability Gate before opening a transaction or
  accessing the ledger. It raises `PaperEntryDenied`. The exception's
  `assessment` carries the gate decision and reason. A027 has no positive
  admission path, so A028 blocks all BUY requests through this entry point.
- **SELL** delegates directly to A006. The checkpoint and balance checks,
  request ID handling, and publication-uncertainty behavior come from the
  coordinator. An uncertain publication still requires inspection before retry.
- **Other actions** raise `ValueError`.

The boundary accepts the caller's existing paper ledger connection. Follow
the coordinator's connection ownership requirements. A denied BUY leaves
the connection's ledger state and anchor untouched. Opening or enrolling a
ledger is outside the operation.

This is a new explicit entry point. The A006 disposable demo, direct ledger
methods, and research replays remain independent entry points. A028 therefore
does not provide system-wide enforcement, resolve the A006 legacy-reopen
enrollment gap, or address Windows checkpoint durability. It grants no live
authority.

Run the targeted tests with:

```sh
PYTHONPATH=app python -m unittest discover -s tests -p 'test_paper_entry_a028.py' -v
```
