"""A006 P3C12: regression for incomplete managed-mode enforcement."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class ManagedReopenBoundaryTests(unittest.TestCase):

    @unittest.expectedFailure
    def test_checkpoint_alone_does_not_protect_legacy_reopen(self):
        """Known gap: checkpoint publication is not managed enrollment."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ledger.sqlite"
            anchor = root / "anchor.json"
            key = b"P3C12-disposable-test-key-32bytes!"

            ledger = DurableLedger(
                database,
                opening_cash="1000.00",
            )
            try:
                ledger.db.execute("BEGIN")
                try:
                    digest = verify_protected_journal(
                        ledger.db,
                        ledger.opening_cash,
                    )
                    sequence = ledger.db.execute(
                        "SELECT COUNT(*) FROM ledger_entries"
                    ).fetchone()[0]
                finally:
                    ledger.db.rollback()
            finally:
                ledger.close()

            write_anchor(
                anchor,
                create_anchor(sequence, digest, key),
                key,
            )

            reopened = DurableLedger(
                database,
                opening_cash="1000.00",
            )
            try:
                with self.assertRaises(RuntimeError):
                    reopened.record_buy(
                        "should-be-blocked",
                        "1",
                        "10",
                    )
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
