"""A006 C2D-04B2C4B1 enrollment-store tests."""

import sqlite3
import unittest
import uuid

from ariyan_trading.authorization_history_writer_policy import (
    create_history_writer_policy,
)
from ariyan_trading.authorization_history_writer_enrollment_store import (
    initialize_enrollment_store,
    read_enrollment_policy,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
)


class HistoryWriterEnrollmentStoreTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:", isolation_level=None
        )
        self.stream_id = str(uuid.uuid4())
        self.digest = opening_history_commitment(self.stream_id)
        self.key = b"A" * 32

        self.policy = create_history_writer_policy(
            self.stream_id, 0, self.digest, self.key
        )

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def initialize(self):
        self.db.execute("BEGIN IMMEDIATE")
        initialize_enrollment_store(self.db, self.policy)
        self.db.commit()

    def test_initialization_and_read(self):
        self.initialize()
        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                read_enrollment_policy(self.db),
                self.policy,
            )
        finally:
            self.db.rollback()

    def test_initialization_requires_transaction(self):
        with self.assertRaises(ValueError):
            initialize_enrollment_store(
                self.db, self.policy
            )

    def test_read_requires_transaction(self):
        self.initialize()
        with self.assertRaises(ValueError):
            read_enrollment_policy(self.db)

    def test_duplicate_initialization_rejected(self):
        self.initialize()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ValueError):
                initialize_enrollment_store(
                    self.db, self.policy
                )
        finally:
            self.db.rollback()

    def test_rollback_removes_table(self):
        self.db.execute("BEGIN IMMEDIATE")
        initialize_enrollment_store(self.db, self.policy)
        self.db.rollback()

        result = self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='auth_writer_enrollment_state'"
        ).fetchall()

        self.assertEqual(result, [])

    def test_missing_policy_rejected(self):
        self.initialize()
        self.db.execute(
            "DELETE FROM auth_writer_enrollment_state"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()

    def test_extra_metadata_rejected(self):
        self.initialize()
        self.db.execute(
            "INSERT INTO auth_writer_enrollment_state "
            "(key,value) VALUES ('extra','value')"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()

    def test_noncanonical_json_rejected(self):
        self.initialize()
        self.db.execute(
            "UPDATE auth_writer_enrollment_state "
            "SET value='{}' WHERE key='policy'"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()

    def test_valid_hex_fields_preserve_original_json(self):
        self.initialize()
        self.db.execute("BEGIN")
        try:
            result = read_enrollment_policy(self.db)
            self.assertEqual(result["mac"], self.policy["mac"])
            self.assertEqual(
                result["enrollment_digest"],
                self.policy["enrollment_digest"],
            )
        finally:
            self.db.rollback()

    def test_noncanonical_valid_policy_json_rejected(self):
        import json

        self.initialize()

        noncanonical = json.dumps(
            self.policy,
            sort_keys=False,
            indent=2,
        )

        self.db.execute(
            "UPDATE auth_writer_enrollment_state "
            "SET value=? WHERE key='policy'",
            (noncanonical,),
        )

        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()

    def test_unexpected_table_rejected(self):
        self.initialize()
        self.db.execute(
            "CREATE TABLE auth_writer_enrollment_extra "
            "(value TEXT)"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()

    def test_temporary_shadow_rejected(self):
        self.initialize()
        self.db.execute(
            "CREATE TEMP TABLE auth_writer_enrollment_state "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                read_enrollment_policy(self.db)
        finally:
            self.db.rollback()


if __name__ == "__main__":
    unittest.main()
