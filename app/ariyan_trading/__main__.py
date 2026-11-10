"""Disposable offline demo using the protected Decimal paper ledger."""

import argparse
from functools import partial
from pathlib import Path
from secrets import token_bytes
from tempfile import TemporaryDirectory

from .checkpoint_coordinator import execute_checkpointed_trade
from .durable_ledger import DurableLedger
from .journal_store import verify_protected_journal
from .paper_entry import (
    PAPER_EXECUTION_STATES, PaperEntryDenied, PaperExecutionDenied, execute_governed_paper_trade,
)
from .trust_anchor import create_anchor, write_anchor


def main(*, governed=False, execution_state="NORMAL"):
    with TemporaryDirectory(prefix="ariyan-paper-demo-") as directory:
        root = Path(directory)
        database = root / "demo.sqlite"
        anchor = root / "demo-checkpoint.json"
        key = token_bytes(32)

        ledger = DurableLedger(database, opening_cash="10000.00")
        try:
            # Explicit enrollment of a new, disposable demo ledger only.
            # Never used to enroll or repair an existing user account.
            ledger.db.execute("BEGIN")
            try:
                digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                ledger.db.commit()
            except BaseException:
                ledger.db.rollback()
                raise
            write_anchor(anchor, create_anchor(0, digest, key), key)

            seed = execute_checkpointed_trade(
                ledger, "BUY", "demo-buy", "1", "100.00",
                anchor_path=anchor, key=key,
            )
            sell = execute_checkpointed_trade
            if governed:
                # The first trade seeded an existing position for this demo.
                # Subsequent orders use the governed boundary.
                sell = partial(execute_governed_paper_trade, execution_state=execution_state)
                try:
                    sell(ledger, "BUY", "demo-blocked-buy", "1", "100.00",
                         anchor_path=anchor, key=key)
                except PaperEntryDenied as exc:
                    denial = f"{exc.assessment['decision']} {exc.assessment['reason']}"
                except PaperExecutionDenied as exc:
                    denial = str(exc)
                else:
                    raise RuntimeError("Governed demo expected BUY to be denied")

            sell_denial = None
            try:
                result = sell(
                    ledger, "SELL", "demo-sell", "1", "101.00",
                    anchor_path=anchor, key=key,
                )
            except PaperExecutionDenied as exc:
                sell_denial = exc
                result = seed
        finally:
            ledger.close()

        reader = DurableLedger(
            database, checkpoint_path=anchor, checkpoint_key=key
        )
        try:
            cash, units = reader.balances()
        finally:
            reader.close()

        if governed and execution_state != "NORMAL":
            print("ARIYAN TRADING AI — A049")
            print("Paper execution state:", execution_state)
        else:
            print("ARIYAN TRADING AI — A029" if governed else "ARIYAN TRADING AI — A006")
        print("MODE: DISPOSABLE OFFLINE PAPER DEMO")
        print("SYNTHETIC PRICES — NO MARKET DATA")
        print("Opening cash: 10000.00")
        if governed:
            print("Synthetic starting position: 1 unit at 100.00")
            print("Governed BUY:", denial)
        else:
            print("Paper BUY: 1 unit at 100.00")
        if sell_denial is None:
            print("Paper SELL: 1 unit at 101.00")
        else:
            print(sell_denial)
        print("Verified cash:", cash)
        print("Verified units:", units)
        print("Checkpoint sequence:", result["sequence"])
        print("Authenticated reopening: PASSED")
        print("Demo excludes fees, slippage, and strategy validation")
        print("NO LIVE FINANCIAL ACTIONS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--governed", action="store_true", help="Exercise the offline paper-entry boundary",
    )
    parser.add_argument("--execution-state", choices=PAPER_EXECUTION_STATES,
                        help="Set the state for the governed offline demo")
    args = parser.parse_args()
    if args.execution_state is not None and not args.governed:
        parser.error("--execution-state requires --governed")
    main(governed=args.governed, execution_state=args.execution_state or "NORMAL")
