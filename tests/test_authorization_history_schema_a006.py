"""A006 C2C4: fail-closed authorization-history schema tests."""

import sqlite3
import unittest
import uuid

from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    verify_history_store,
)


class AuthorizationHistorySchemaTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )

        self.stream_id = str(uuid.uuid4())

        self.db.execute("BEGIN IMMEDIATE")

        initialize_history_store(
            self.db,
            self.stream_id,
        )

        self.db.execute("COMMIT")

    def tearDown(self):
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")

        self.db.close()

    def verify(self):
        self.db.execute("BEGIN")

        try:
            return verify_history_store(
                self.db,
                self.stream_id,
            )

        finally:
            self.db.execute("ROLLBACK")

    def test_initialization_rejects_temp_shadow(self):
        db = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )

        try:
            db.execute("""
                CREATE TEMP TABLE authorization_history_entries (
                    history_sequence INTEGER PRIMARY KEY,
                    payload BLOB NOT NULL
                )
            """)

            db.execute("BEGIN IMMEDIATE")

            with self.assertRaises(ValueError):
                initialize_history_store(
                    db,
                    str(uuid.uuid4()),
                )

            permanent_tables = db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table'"
            ).fetchall()

            self.assertFalse(
                [
                    name
                    for (name,) in permanent_tables
                    if name.startswith("authorization_history_")
                ]
            )

        finally:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()

    def test_clean_schema_accepted(self):
        sequence, digest = self.verify()

        self.assertEqual(sequence, 0)
        self.assertEqual(len(digest), 64)

    def test_unexpected_trigger_rejected(self):
        self.db.execute("""
            CREATE TRIGGER unexpected_history_trigger
            AFTER INSERT ON authorization_history_entries
            BEGIN
                SELECT 1;
            END
        """)

        with self.assertRaises(ValueError):
            self.verify()

    def test_unexpected_temp_trigger_rejected(self):
        self.db.execute("""
            CREATE TEMP TRIGGER unexpected_temp_history_trigger
            AFTER INSERT ON authorization_history_entries
            BEGIN
                SELECT 1;
            END
        """)

        with self.assertRaises(ValueError):
            self.verify()

    def test_temporary_table_shadowing_rejected(self):
        self.db.execute("""
            CREATE TEMP TABLE authorization_history_entries (
                history_sequence INTEGER PRIMARY KEY,
                payload BLOB NOT NULL
            )
        """)

        with self.assertRaises(ValueError):
            self.verify()

    def test_unexpected_column_rejected(self):
        self.db.execute("""
            ALTER TABLE authorization_history_entries
            ADD COLUMN unexpected TEXT
        """)

        with self.assertRaises(ValueError):
            self.verify()

    def test_unexpected_index_rejected(self):
        self.db.execute("""
            CREATE INDEX unexpected_history_index
            ON authorization_history_entries(payload)
        """)

        with self.assertRaises(ValueError):
            self.verify()


if __name__ == "__main__":
    unittest.main()
