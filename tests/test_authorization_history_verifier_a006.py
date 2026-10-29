"""A006 C2D authenticated history verification tests."""

import sqlite3
import unittest
import uuid

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_verifier import (
    verify_authenticated_history,
)
from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    VERSION as OBS_VERSION,
    AuthorizationStatusObservation,
)
from ariyan_trading.authorization_status_history import (
    VERSION as HISTORY_VERSION,
    AuthorizationStatusHistoryEntry,
)
from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    append_history_entry,
    verify_history_store,
)


class AuthenticatedHistoryVerifierTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )
        self.stream_id = str(uuid.uuid4())
        self.key = b"H" * 32

        self.db.execute("BEGIN IMMEDIATE")
        initialize_history_store(self.db, self.stream_id)
        self.db.execute("COMMIT")

    def tearDown(self):
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")
        self.db.close()

    def entry(self, sequence):
        status = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        observation = AuthorizationStatusObservation(
            version=OBS_VERSION,
            status_record=status,
            source_id="source-1",
            sequence=sequence,
            observed_at=100 + sequence,
            valid_until=200 + sequence,
        )

        return AuthorizationStatusHistoryEntry(
            version=HISTORY_VERSION,
            stream_id=self.stream_id,
            history_sequence=sequence,
            observation=observation,
        )

    def append(self, sequence):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(sequence),
            )
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def current_anchor(self):
        self.db.execute("BEGIN")
        try:
            sequence, digest = verify_history_store(
                self.db,
                self.stream_id,
            )
        finally:
            self.db.execute("ROLLBACK")

        return create_history_anchor(
            self.stream_id,
            sequence,
            digest,
            self.key,
        )

    def verify(self, anchor, key=None, stream_id=None):
        self.db.execute("BEGIN")
        try:
            return verify_authenticated_history(
                self.db,
                stream_id or self.stream_id,
                anchor,
                self.key if key is None else key,
            )
        finally:
            self.db.execute("ROLLBACK")

    def test_empty_history_accepted(self):
        anchor = self.current_anchor()

        self.assertEqual(
            self.verify(anchor),
            (0, anchor["history_digest"]),
        )

    def test_single_entry_accepted(self):
        self.append(1)
        anchor = self.current_anchor()

        self.assertEqual(
            self.verify(anchor),
            (1, anchor["history_digest"]),
        )

    def test_multiple_entries_accepted(self):
        self.append(1)
        self.append(2)

        anchor = self.current_anchor()

        self.assertEqual(
            self.verify(anchor),
            (2, anchor["history_digest"]),
        )

    def test_transaction_required(self):
        anchor = self.current_anchor()

        with self.assertRaises(ValueError):
            verify_authenticated_history(
                self.db,
                self.stream_id,
                anchor,
                self.key,
            )

    def test_wrong_key_rejected(self):
        anchor = self.current_anchor()

        with self.assertRaises(ValueError):
            self.verify(anchor, key=b"W" * 32)

    def test_missing_anchor_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(None)

    def test_wrong_stream_rejected(self):
        anchor = self.current_anchor()

        with self.assertRaises(ValueError):
            self.verify(
                anchor,
                stream_id=str(uuid.uuid4()),
            )

    def test_old_anchor_rejected_after_append(self):
        old_anchor = self.current_anchor()

        self.append(1)

        with self.assertRaises(ValueError):
            self.verify(old_anchor)

    def test_future_sequence_rejected(self):
        anchor = self.current_anchor()

        future = create_history_anchor(
            self.stream_id,
            5,
            anchor["history_digest"],
            self.key,
        )

        with self.assertRaises(ValueError):
            self.verify(future)

    def test_wrong_digest_rejected(self):
        anchor = self.current_anchor()

        wrong = create_history_anchor(
            self.stream_id,
            0,
            "0" * 64,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.verify(wrong)

    def test_corrupted_history_rejected(self):
        self.append(1)
        anchor = self.current_anchor()

        self.db.execute(
            "UPDATE authorization_history_commitments "
            "SET digest=? WHERE history_sequence=1",
            ("0" * 64,),
        )

        with self.assertRaises(ValueError):
            self.verify(anchor)

    def test_verification_does_not_mutate_database(self):
        self.append(1)
        anchor = self.current_anchor()

        before = self.db.iterdump()
        before_sql = list(before)

        self.verify(anchor)

        after_sql = list(self.db.iterdump())

        self.assertEqual(before_sql, after_sql)


if __name__ == "__main__":
    unittest.main()
