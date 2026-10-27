"""Disposable offline demo using the protected Decimal paper ledger."""

from pathlib import Path
from secrets import token_bytes
from tempfile import TemporaryDirectory

from .checkpoint_coordinator import execute_checkpointed_trade
from .durable_ledger import DurableLedger
from .journal_store import verify_protected_journal
from .trust_anchor import create_anchor, write_anchor


def main():
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

            execute_checkpointed_trade(
                ledger, "BUY", "demo-buy", "1", "100.00",
                anchor_path=anchor, key=key,
            )
            result = execute_checkpointed_trade(
                ledger, "SELL", "demo-sell", "1", "101.00",
                anchor_path=anchor, key=key,
            )
        finally:
            ledger.close()

        reader = DurableLedger(
            database, checkpoint_path=anchor, checkpoint_key=key
        )
        try:
            cash, units = reader.balances()
        finally:
            reader.close()

        print("ARIYAN TRADING AI — A006")
        print("MODE: DISPOSABLE OFFLINE PAPER DEMO")
        print("SYNTHETIC PRICES — NO MARKET DATA")
        print("Opening cash: 10000.00")
        print("Paper BUY: 1 unit at 100.00")
        print("Paper SELL: 1 unit at 101.00")
        print("Verified cash:", cash)
        print("Verified units:", units)
        print("Checkpoint sequence:", result["sequence"])
        print("Authenticated reopening: PASSED")
        print("Demo excludes fees, slippage, and strategy validation")
        print("NO LIVE FINANCIAL ACTIONS")


if __name__ == "__main__":
    main()
