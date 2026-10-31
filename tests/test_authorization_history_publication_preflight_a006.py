"""A006 C2D-04B2C1 authenticated preflight tests."""

import sqlite3
import unittest
from uuid import uuid4

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
)
from ariyan_trading.authorization_history_publication_preflight import (
    verify_history_publication_preflight,
)
from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    verify_history_store,
)


class HistoryPublicationPreflightTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )
        self.stream_id = str(uuid4())
        self.key = b"P" * 32

        self.db.execute("BEGIN IMMEDIATE")
        initialize_history_store(self.db, self.stream_id)
        initialize_publication_control(self.db)
        self.db.commit()

        self.db.execute("BEGIN")
        sequence, digest = verify_history_store(
            self.db, self.stream_id
        )
        self.db.rollback()

        self.anchor = create_history_anchor(
            self.stream_id,
            sequence,
            digest,
            self.key,
        )

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def verify(self, anchor=None, key=None, stream_id=None):
        self.db.execute("BEGIN")
        try:
            return verify_history_publication_preflight(
                self.db,
                self.stream_id if stream_id is None else stream_id,
                self.anchor if anchor is None else anchor,
                self.key if key is None else key,
            )
        finally:
            self.db.rollback()

    def test_valid_genesis_accepted(self):
        self.assertEqual(
            self.verify(),
            (0, self.anchor["history_digest"]),
        )

    def test_active_transaction_required(self):
        with self.assertRaises(ValueError):
            verify_history_publication_preflight(
                self.db,
                self.stream_id,
                self.anchor,
                self.key,
            )

    def test_wrong_key_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(key=b"Q" * 32)

    def test_wrong_stream_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(stream_id=str(uuid4()))

    def test_authenticated_anchor_stream_mismatch(self):
        other = create_history_anchor(
            str(uuid4()),
            0,
            self.anchor["history_digest"],
            self.key,
        )
        with self.assertRaises(ValueError):
            self.verify(anchor=other)

    def test_tampered_anchor_rejected(self):
        tampered = dict(self.anchor)
        tampered["history_digest"] = "f" * 64

        with self.assertRaises(ValueError):
            self.verify(anchor=tampered)

    def test_stale_anchor_rejected(self):
        stale = create_history_anchor(
            self.stream_id,
            1,
            "a" * 64,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.verify(anchor=stale)

    def test_pending_state_rejected(self):
        self.db.execute(
            "UPDATE auth_pubctl_state "
            "SET value='PENDING' "
            "WHERE key='publication_state'"
        )

        with self.assertRaises(ValueError):
            self.verify()

    def test_extra_metadata_rejected(self):
        self.db.execute(
            "INSERT INTO auth_pubctl_state(key,value) "
            "VALUES ('unexpected','value')"
        )

        with self.assertRaises(ValueError):
            self.verify()

    def test_schema_shadow_rejected(self):
        self.db.execute(
            "CREATE TEMP TABLE auth_pubctl_state "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )

        with self.assertRaises(ValueError):
            self.verify()

    def test_success_does_not_mutate_database(self):
        before = self.db.total_changes

        self.assertEqual(
            self.verify(),
            (0, self.anchor["history_digest"]),
        )

        self.assertEqual(self.db.total_changes, before)


if __name__ == "__main__":
    unittest.main()
