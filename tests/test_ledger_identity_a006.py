"""A006-WB02-P3A persistent ledger identity tests."""

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.ledger_identity import (
    initialize_ledger_identity,
    read_ledger_identity,
    validate_ledger_identity,
)


class LedgerIdentityTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ledger.sqlite"

    def open_ledger(self):
        return DurableLedger(self.path, opening_cash="1000.00")

    def test_new_ledger_has_canonical_uuid4(self):
        ledger = self.open_ledger()
        try:
            identity = ledger.ledger_identity
            self.assertEqual(str(uuid.UUID(identity)), identity)
            self.assertEqual(uuid.UUID(identity).version, 4)
        finally:
            ledger.db.close()

    def test_identity_persists_after_reopen(self):
        ledger = self.open_ledger()
        identity = ledger.ledger_identity
        ledger.db.close()

        reopened = self.open_ledger()
        try:
            self.assertEqual(reopened.ledger_identity, identity)
        finally:
            reopened.db.close()

    def test_distinct_ledgers_have_distinct_identities(self):
        first = self.open_ledger()
        first_id = first.ledger_identity
        first.db.close()

        other_path = Path(self.temp.name) / "other.sqlite"
        second = DurableLedger(
            other_path, opening_cash="1000.00"
        )
        try:
            self.assertNotEqual(first_id, second.ledger_identity)
        finally:
            second.db.close()

    def test_invalid_identity_rejected_on_reopen(self):
        ledger = self.open_ledger()
        ledger.db.close()

        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE ledger_meta SET value=? "
                "WHERE key='ledger_identity'",
                ("invalid-identity",),
            )

        with self.assertRaises(ValueError):
            self.open_ledger()

    def test_uuid1_identity_rejected(self):
        with self.assertRaises(ValueError):
            validate_ledger_identity(str(uuid.uuid1()))

    def test_uppercase_identity_rejected(self):
        with self.assertRaises(ValueError):
            validate_ledger_identity(str(uuid.uuid4()).upper())

    def test_duplicate_initialization_rejected(self):
        ledger = self.open_ledger()
        try:
            ledger.db.execute("BEGIN IMMEDIATE")
            with self.assertRaises(ValueError):
                initialize_ledger_identity(ledger.db)
            ledger.db.execute("ROLLBACK")
        finally:
            ledger.db.close()

    def test_initialization_requires_transaction(self):
        ledger = self.open_ledger()
        try:
            with self.assertRaises(ValueError):
                initialize_ledger_identity(ledger.db)
        finally:
            ledger.db.close()

    def test_legacy_missing_identity_is_not_auto_enrolled(self):
        ledger = self.open_ledger()
        ledger.db.close()

        with sqlite3.connect(self.path) as db:
            db.execute(
                "DELETE FROM ledger_meta "
                "WHERE key='ledger_identity'"
            )

        reopened = self.open_ledger()
        try:
            self.assertIsNone(reopened.ledger_identity)
            self.assertIsNone(
                read_ledger_identity(reopened.db)
            )
        finally:
            reopened.db.close()


if __name__ == "__main__":
    unittest.main()
