"""A006 regression: rejected trades preserve journal integrity."""

import tempfile
import unittest
from pathlib import Path

from app.ariyan_trading.durable_ledger import DurableLedger
from app.ariyan_trading.journal_store import verify_protected_journal


class TradeRollbackA006Tests(unittest.TestCase):

    def test_insufficient_cash_preserves_journal(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = DurableLedger(
                Path(directory) / "ledger.sqlite",
                opening_cash="1000",
            )
            try:
                before_digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                before_count = ledger.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]

                with self.assertRaisesRegex(
                    ValueError, "Insufficient cash"
                ):
                    ledger.record_buy(
                        "rejected-trade", "1", "2000"
                    )

                after_digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                after_count = ledger.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]

                self.assertEqual(before_count, after_count)
                self.assertEqual(before_digest, after_digest)
                self.assertFalse(ledger.db.in_transaction)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
