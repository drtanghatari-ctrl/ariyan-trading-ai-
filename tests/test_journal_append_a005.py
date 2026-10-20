import sqlite3
import unittest

from ariyan_trading.journal_store import (
    append_journal_commitment,
    create_protected_journal,
    verify_protected_journal,
)


class JournalAppendA005Tests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:", isolation_level=None
        )

        self.db.execute(
            "CREATE TABLE ledger_meta ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL)"
        )

        self.db.execute(
            "CREATE TABLE ledger_entries ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "request_id TEXT NOT NULL UNIQUE, "
            "action TEXT NOT NULL "
            "CHECK(action IN ('BUY','SELL')), "
            "quantity TEXT NOT NULL, "
            "price TEXT NOT NULL, "
            "cash_delta TEXT NOT NULL, "
            "units_delta TEXT NOT NULL)"
        )

        self.db.execute("BEGIN IMMEDIATE")
        create_protected_journal(self.db, "100.00")
        self.db.execute("COMMIT")

    def tearDown(self):
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")
        self.db.close()

    def insert_buy(self, request_id="buy-001"):
        self.db.execute(
            "INSERT INTO ledger_entries "
            "(request_id,action,quantity,price,"
            "cash_delta,units_delta) "
            "VALUES (?,?,?,?,?,?)",
            (request_id, "BUY", "2", "10", "-20", "2"),
        )

    def test_valid_append(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.insert_buy()
        digest = append_journal_commitment(
            self.db, "100.00"
        )
        self.db.execute("COMMIT")

        self.assertEqual(
            verify_protected_journal(self.db, "100.00"),
            digest,
        )

    def test_duplicate_append_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.insert_buy()
        append_journal_commitment(self.db, "100.00")

        with self.assertRaises(ValueError):
            append_journal_commitment(self.db, "100.00")

    def test_append_requires_transaction(self):
        with self.assertRaises(ValueError):
            append_journal_commitment(self.db, "100.00")

    def test_prior_history_tampering_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.insert_buy()
        append_journal_commitment(self.db, "100.00")
        self.db.execute("COMMIT")

        self.db.execute(
            "UPDATE ledger_entries "
            "SET quantity='1',cash_delta='-10',"
            "units_delta='1' WHERE sequence=1"
        )

        self.db.execute("BEGIN IMMEDIATE")
        self.insert_buy("buy-002")

        with self.assertRaises(ValueError):
            append_journal_commitment(self.db, "100.00")

    def test_rollback_removes_trade_and_commitment(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.insert_buy()
        append_journal_commitment(self.db, "100.00")
        self.db.execute("ROLLBACK")

        entries = self.db.execute(
            "SELECT COUNT(*) FROM ledger_entries"
        ).fetchone()[0]

        commitments = self.db.execute(
            "SELECT COUNT(*) FROM journal_commitments"
        ).fetchone()[0]

        self.assertEqual(entries, 0)
        self.assertEqual(commitments, 0)

        verify_protected_journal(self.db, "100.00")


if __name__ == "__main__":
    unittest.main()
