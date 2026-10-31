"""A006 C2D-04B2C2 atomic preparation tests."""

import sqlite3
import unittest
from uuid import uuid4

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_prepare_coordinator import (
    HistoryPreparationUncertain,
    prepare_history_publication,
)
from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
    verify_publication_control,
)
from ariyan_trading.authorization_history_publication_store import (
    verify_pending_publication_intent,
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
    verify_history_store,
)


class CommitFaultConnection:
    """Inject a failure immediately before or after SQLite COMMIT."""

    def __init__(self, db, after_commit):
        self.db = db
        self.after_commit = after_commit

    def __getattr__(self, name):
        return getattr(self.db, name)

    def execute(self, sql, *args):
        if sql == "COMMIT":
            if not self.after_commit:
                raise RuntimeError("Injected pre-commit failure")
            result = self.db.execute(sql, *args)
            raise RuntimeError("Injected post-commit failure")
        return self.db.execute(sql, *args)


class HistoryPrepareTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:", isolation_level=None
        )
        self.db.execute("PRAGMA synchronous=FULL")
        self.stream_id = str(uuid4())
        self.key = b"C" * 32

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
            self.stream_id, sequence, digest, self.key
        )

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def entry(self, sequence=1):
        status = AuthorizationStatusRecord(
            authorization_id=str(uuid4()),
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

    def prepare(self, entry=None, db=None, anchor=None):
        return prepare_history_publication(
            self.db if db is None else db,
            self.stream_id,
            self.entry() if entry is None else entry,
            self.anchor if anchor is None else anchor,
            self.key,
        )

    def inspect(self):
        self.db.execute("BEGIN")
        try:
            tip = verify_history_store(
                self.db, self.stream_id
            )
            rows = dict(self.db.execute(
                "SELECT key,value FROM auth_pubctl_state"
            ).fetchall())
            return tip, rows
        finally:
            self.db.rollback()

    def test_success_is_pending_not_published(self):
        result = self.prepare()
        self.assertEqual(
            result["state"], "PENDING_PUBLICATION"
        )
        self.assertEqual(result["sequence"], 1)

        tip, rows = self.inspect()
        self.assertEqual(tip, (1, result["digest"]))
        self.assertEqual(
            rows["publication_state"], "PENDING"
        )

        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                verify_pending_publication_intent(
                    self.db, self.stream_id
                ),
                result["intent"],
            )
        finally:
            self.db.rollback()

    def test_second_preparation_rejected(self):
        self.prepare()
        with self.assertRaises(ValueError):
            self.prepare(entry=self.entry(2))
        self.assertEqual(self.inspect()[0][0], 1)

    def test_invalid_sequence_rolls_back(self):
        with self.assertRaises(ValueError):
            self.prepare(entry=self.entry(2))
        tip, rows = self.inspect()
        self.assertEqual(tip[0], 0)
        self.assertEqual(
            rows["publication_state"], "READY"
        )

    def test_wrong_key_anchor_rejected(self):
        wrong = create_history_anchor(
            self.stream_id,
            0,
            self.anchor["history_digest"],
            b"Z" * 32,
        )
        with self.assertRaises(ValueError):
            self.prepare(anchor=wrong)
        self.assertEqual(self.inspect()[0][0], 0)

    def test_idle_connection_required(self):
        self.db.execute("BEGIN")
        with self.assertRaises(ValueError):
            self.prepare()
        self.db.rollback()
        self.assertEqual(self.inspect()[0][0], 0)

    def test_full_synchronous_required(self):
        self.db.execute("PRAGMA synchronous=NORMAL")
        with self.assertRaises(ValueError):
            self.prepare()
        self.assertEqual(self.inspect()[0][0], 0)

    def test_precommit_failure_is_uncertain(self):
        proxy = CommitFaultConnection(
            self.db, after_commit=False
        )
        with self.assertRaises(HistoryPreparationUncertain):
            self.prepare(db=proxy)

        tip, rows = self.inspect()
        self.assertEqual(tip[0], 0)
        self.assertEqual(
            rows["publication_state"], "READY"
        )

    def test_postcommit_failure_is_uncertain(self):
        proxy = CommitFaultConnection(
            self.db, after_commit=True
        )
        with self.assertRaises(HistoryPreparationUncertain):
            self.prepare(db=proxy)

        tip, rows = self.inspect()
        self.assertEqual(tip[0], 1)
        self.assertEqual(
            rows["publication_state"], "PENDING"
        )

    def test_no_automatic_retry_after_uncertainty(self):
        proxy = CommitFaultConnection(
            self.db, after_commit=True
        )
        with self.assertRaises(HistoryPreparationUncertain):
            self.prepare(db=proxy)

        with self.assertRaises(ValueError):
            self.prepare(entry=self.entry(2))

        self.assertEqual(self.inspect()[0][0], 1)

    def test_previous_anchor_unchanged(self):
        original = dict(self.anchor)
        self.prepare()
        self.assertEqual(self.anchor, original)

    def test_success_leaves_connection_idle(self):
        self.prepare()
        self.assertFalse(self.db.in_transaction)


    def test_precommit_failure_and_rollback_failure_uncertain(self):
        class RollbackFaultConnection(CommitFaultConnection):
            def rollback(self):
                raise RuntimeError("Injected rollback failure")

        proxy = RollbackFaultConnection(
            self.db, after_commit=False
        )

        with self.assertRaises(HistoryPreparationUncertain) as caught:
            self.prepare(db=proxy)

        self.assertIn(
            "Injected pre-commit failure",
            str(caught.exception.__cause__),
        )

        self.assertTrue(self.db.in_transaction)

        self.db.rollback()

        tip, rows = self.inspect()
        self.assertEqual(tip[0], 0)
        self.assertEqual(rows["publication_state"], "READY")

    def test_postcommit_failure_and_rollback_failure_uncertain(self):
        class RollbackFaultConnection(CommitFaultConnection):
            def rollback(self):
                raise RuntimeError("Injected rollback failure")

        proxy = RollbackFaultConnection(
            self.db, after_commit=True
        )

        with self.assertRaises(HistoryPreparationUncertain) as caught:
            self.prepare(db=proxy)

        self.assertIn(
            "Injected post-commit failure",
            str(caught.exception.__cause__),
        )

        tip, rows = self.inspect()
        self.assertEqual(tip[0], 1)
        self.assertEqual(rows["publication_state"], "PENDING")


if __name__ == "__main__":
    unittest.main()
