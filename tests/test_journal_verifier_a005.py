import sqlite3
import unittest

from ariyan_trading.journal_commitment import (
    opening_commitment,
    entry_commitment,
)
from ariyan_trading.journal_store import (
    create_protected_journal,
    verify_protected_journal,
)


class JournalVerifierA005Tests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")

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

        create_protected_journal(self.db, "100.00")

        self.db.execute(
            "INSERT INTO ledger_entries "
            "(request_id,action,quantity,price,"
            "cash_delta,units_delta) "
            "VALUES (?,?,?,?,?,?)",
            ("buy-001", "BUY", "2", "10", "-20", "2"),
        )

        self.genesis = opening_commitment("100.00")

        self.digest = entry_commitment(
            self.genesis,
            1,
            "buy-001",
            "BUY",
            "2",
            "10",
            "-20",
            "2",
        )

        self.db.execute(
            "INSERT INTO journal_commitments "
            "(sequence,digest) VALUES (?,?)",
            (1, self.digest),
        )

    def tearDown(self):
        self.db.close()

    def test_valid_journal_accepted(self):
        result = verify_protected_journal(
            self.db, "100.00"
        )
        self.assertEqual(result, self.digest)

    def test_consistent_financial_rewrite_rejected(self):
        self.db.execute(
            "UPDATE ledger_entries "
            "SET quantity='1',cash_delta='-10',"
            "units_delta='1' WHERE sequence=1"
        )
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "100.00")

    def test_missing_commitment_rejected(self):
        self.db.execute(
            "DELETE FROM journal_commitments"
        )
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "100.00")

    def test_modified_digest_rejected(self):
        self.db.execute(
            "UPDATE journal_commitments "
            "SET digest=? WHERE sequence=1",
            ("0" * 64,),
        )
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "100.00")

    def test_opening_balance_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "200.00")

    def test_extra_commitment_rejected(self):
        self.db.execute(
            "INSERT INTO journal_commitments "
            "(sequence,digest) VALUES (?,?)",
            (2, "0" * 64),
        )
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "100.00")

    def test_modified_request_id_rejected(self):
        self.db.execute(
            "UPDATE ledger_entries "
            "SET request_id='changed' WHERE sequence=1"
        )
        with self.assertRaises(ValueError):
            verify_protected_journal(self.db, "100.00")


if __name__ == "__main__":
    unittest.main()
