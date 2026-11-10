# A050 load an authenticated paper state after reopening

Create the file once using the ledger's persistent UUID and separately
protected checkpoint key:

```python
from ariyan_trading.paper_execution_state import create_paper_execution_state

create_paper_execution_state(
    state_path, ledger.ledger_identity, "FREEZE", key=checkpoint_key,
)
```

Pass the same path as `execution_state_path` when calling
`execute_governed_paper_trade`. Omit the explicit `execution_state` argument.
The governed path verifies the stored record against the reopened ledger's
identity and the supplied key before accessing SQL or the anchor. A missing,
corrupted, or foreign state file causes an error without submitting the order.
An authenticated STOP still delegates SELL to the A006 coordinator.

The file contains a canonical ASCII JSON record and a domain-separated
HMAC-SHA-256. Creation is exclusive and synchronizes file contents. A failed
or interrupted creation can leave an incomplete record that the reader will
reject. Create it under a trusted local directory. This checkpoint verifies
ordinary close and reopen behavior. Power-loss durability, authorized state
transitions, key custody, rollback detection, and coordination with in-flight
orders remain separate. Older valid records can be restored under the same
key. Calls that omit the state path retain the A049 paper behavior.

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a050.py' -v
```
