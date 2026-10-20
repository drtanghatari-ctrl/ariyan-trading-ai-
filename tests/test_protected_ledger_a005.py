import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal


class ProtectedLedgerA005Tests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "paper.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def counts(self, ledger):
        return (
            ledger.db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0],
            ledger.db.execute(
                "SELECT COUNT(*) FROM journal_commitments"
            ).fetchone()[0],
        )

    def test_new_ledger_protected(self):
        ledger = DurableLedger(self.path, "100.00")
        try:
            self.assertEqual(
                ledger.journal_protection, "protected"
            )
            self.assertEqual(self.counts(ledger), (0, 0))
            verify_protected_journal(
                ledger.db, ledger.opening_cash
            )
        finally:
            ledger.close()

    def test_buy_sell_commitments_survive_restart(self):
        ledger = DurableLedger(self.path, "100.00")
        try:
            ledger.record_buy("buy-1", "2", "10")
            ledger.record_sell("sell-1", "1", "15")
            self.assertEqual(self.counts(ledger), (2, 2))
        finally:
            ledger.close()

        reopened = DurableLedger(self.path)
        try:
            self.assertEqual(
                reopened.journal_protection, "protected"
            )
            self.assertEqual(self.counts(reopened), (2, 2))
            verify_protected_journal(
                reopened.db, reopened.opening_cash
            )
        finally:
            reopened.close()

    def test_rejected_buy_leaves_no_commitment(self):
        ledger = DurableLedger(self.path, "100.00")
        try:
            with self.assertRaises(ValueError):
                ledger.record_buy("too-large", "20", "10")
            self.assertEqual(self.counts(ledger), (0, 0))
            verify_protected_journal(
                ledger.db, ledger.opening_cash
            )
        finally:
            ledger.close()

    def test_rejected_sell_preserves_committed_history(self):
        ledger = DurableLedger(self.path, "100.00")
        try:
            ledger.record_buy("buy-1", "2", "10")
            with self.assertRaises(ValueError):
                ledger.record_sell("oversell", "3", "10")
            self.assertEqual(self.counts(ledger), (1, 1))
            verify_protected_journal(
                ledger.db, ledger.opening_cash
            )
        finally:
            ledger.close()


if __name__ == "__main__":
    unittest.main()
