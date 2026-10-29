import sqlite3
import unittest
import uuid

from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    verify_history_store,
)


class AuthorizationStatusHistoryStoreTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.stream_id = str(uuid.uuid4())

    def tearDown(self):
        self.db.close()

    def initialize(self):
        self.db.execute("BEGIN IMMEDIATE")
        genesis = initialize_history_store(self.db, self.stream_id)
        self.db.execute("COMMIT")
        return genesis

    def test_initialization_requires_transaction(self):
        with self.assertRaises(ValueError):
            initialize_history_store(self.db, self.stream_id)

    def test_verification_requires_transaction(self):
        self.initialize()

        with self.assertRaises(ValueError):
            verify_history_store(self.db, self.stream_id)

    def test_empty_history_verifies(self):
        genesis = self.initialize()

        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                verify_history_store(self.db, self.stream_id),
                (0, genesis),
            )
        finally:
            self.db.execute("ROLLBACK")

    def test_duplicate_initialization_rejected(self):
        self.initialize()

        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ValueError):
                initialize_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")

    def test_incomplete_schema_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "CREATE TABLE authorization_history_meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.db.execute("COMMIT")

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")

    def test_metadata_tampering_rejected(self):
        self.initialize()

        self.db.execute(
            "UPDATE authorization_history_meta "
            "SET value='invalid' WHERE key='stream_id'"
        )

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")

    def test_wrong_stream_rejected(self):
        self.initialize()

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_history_store(
                    self.db,
                    str(uuid.uuid4()),
                )
        finally:
            self.db.execute("ROLLBACK")

    def test_initialization_rollback_removes_tables(self):
        self.db.execute("BEGIN IMMEDIATE")
        initialize_history_store(self.db, self.stream_id)
        self.db.execute("ROLLBACK")

        tables = self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'authorization_history_%'"
        ).fetchall()

        self.assertEqual(tables, [])

    def test_incomplete_metadata_rejected(self):
        self.initialize()

        self.db.execute(
            "DELETE FROM authorization_history_meta "
            "WHERE key='genesis_digest'"
        )

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")

    def test_extra_metadata_rejected(self):
        self.initialize()

        self.db.execute(
            "INSERT INTO authorization_history_meta(key,value) "
            "VALUES ('unexpected','value')"
        )

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")


if __name__ == "__main__":
    unittest.main()
