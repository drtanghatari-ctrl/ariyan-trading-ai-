"""A006 C2D-04B1 publication-control schema tests."""

import sqlite3
import unittest

from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
    verify_publication_control,
)


class PublicationControlTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def initialize(self):
        self.db.execute("BEGIN IMMEDIATE")
        initialize_publication_control(self.db)
        self.db.commit()

    def test_initialization_and_verification(self):
        self.initialize()
        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                verify_publication_control(self.db),
                "READY",
            )
        finally:
            self.db.rollback()

    def test_initialization_requires_transaction(self):
        with self.assertRaises(ValueError):
            initialize_publication_control(self.db)

    def test_verification_requires_transaction(self):
        self.initialize()
        with self.assertRaises(ValueError):
            verify_publication_control(self.db)

    def test_duplicate_initialization_rejected(self):
        self.initialize()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(ValueError):
                initialize_publication_control(self.db)
        finally:
            self.db.rollback()

    def test_initialization_rollback_removes_table(self):
        self.db.execute("BEGIN IMMEDIATE")
        initialize_publication_control(self.db)
        self.db.rollback()

        tables = self.db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name='auth_pubctl_state'"
        ).fetchall()

        self.assertEqual(tables, [])

    def test_missing_metadata_rejected(self):
        self.initialize()
        self.db.execute(
            "DELETE FROM auth_pubctl_state "
            "WHERE key='publication_state'"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_publication_control(self.db)
        finally:
            self.db.rollback()

    def test_extra_metadata_rejected(self):
        self.initialize()
        self.db.execute(
            "INSERT INTO auth_pubctl_state(key,value) "
            "VALUES ('unexpected','value')"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_publication_control(self.db)
        finally:
            self.db.rollback()

    def test_modified_state_rejected(self):
        self.initialize()
        self.db.execute(
            "UPDATE auth_pubctl_state SET value='PENDING' "
            "WHERE key='publication_state'"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_publication_control(self.db)
        finally:
            self.db.rollback()

    def test_unexpected_table_rejected(self):
        self.initialize()
        self.db.execute(
            "CREATE TABLE auth_pubctl_unexpected (value TEXT)"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_publication_control(self.db)
        finally:
            self.db.rollback()

    def test_temporary_shadow_rejected(self):
        self.initialize()
        self.db.execute(
            "CREATE TEMP TABLE auth_pubctl_state "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self.db.execute("BEGIN")
        try:
            with self.assertRaises(ValueError):
                verify_publication_control(self.db)
        finally:
            self.db.rollback()


if __name__ == "__main__":
    unittest.main()
