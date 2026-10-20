import sqlite3
import unittest

from ariyan_trading.journal_commitment import (
    opening_commitment,
)
from ariyan_trading.journal_store import (
    VERSION,
    create_protected_journal,
    protection_status,
)


class JournalStoreA005Tests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE ledger_meta ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL)"
        )

    def tearDown(self):
        self.db.close()

    def test_legacy_database_remains_unsealed(self):
        self.assertEqual(
            protection_status(self.db),
            "legacy-unsealed",
        )

    def test_new_protected_journal(self):
        create_protected_journal(self.db, "100.00")

        self.assertEqual(
            protection_status(self.db),
            "protected",
        )

        genesis = self.db.execute(
            "SELECT value FROM ledger_meta "
            "WHERE key='journal_genesis'"
        ).fetchone()[0]

        self.assertEqual(
            genesis,
            opening_commitment("100.00"),
        )

    def test_protection_version_is_recorded(self):
        create_protected_journal(self.db, "100.00")

        version = self.db.execute(
            "SELECT value FROM ledger_meta "
            "WHERE key='journal_protection'"
        ).fetchone()[0]

        self.assertEqual(version, VERSION)

    def test_missing_commitment_table_rejected(self):
        create_protected_journal(self.db, "100.00")
        self.db.execute(
            "DROP TABLE journal_commitments"
        )

        with self.assertRaises(ValueError):
            protection_status(self.db)

    def test_missing_genesis_rejected(self):
        create_protected_journal(self.db, "100.00")
        self.db.execute(
            "DELETE FROM ledger_meta "
            "WHERE key='journal_genesis'"
        )

        with self.assertRaises(ValueError):
            protection_status(self.db)

    def test_unsupported_version_rejected(self):
        create_protected_journal(self.db, "100.00")
        self.db.execute(
            "UPDATE ledger_meta "
            "SET value='unsupported-version' "
            "WHERE key='journal_protection'"
        )

        with self.assertRaises(ValueError):
            protection_status(self.db)


if __name__ == "__main__":
    unittest.main()
