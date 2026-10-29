import sqlite3
import unittest
import uuid

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
    append_history_entry,
)


class AuthorizationStatusHistoryAppendTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.stream_id = str(uuid.uuid4())

        self.db.execute("BEGIN IMMEDIATE")
        initialize_history_store(self.db, self.stream_id)
        self.db.execute("COMMIT")

    def tearDown(self):
        if self.db.in_transaction:
            self.db.execute("ROLLBACK")
        self.db.close()

    def entry(self, sequence, stream_id=None):
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
            stream_id=stream_id or self.stream_id,
            history_sequence=sequence,
            observation=observation,
        )

    def append_and_commit(self, entry):
        self.db.execute("BEGIN IMMEDIATE")
        result = append_history_entry(
            self.db,
            self.stream_id,
            entry,
        )
        self.db.execute("COMMIT")
        return result

    def verify(self):
        self.db.execute("BEGIN")
        try:
            return verify_history_store(self.db, self.stream_id)
        finally:
            self.db.execute("ROLLBACK")

    def test_single_append(self):
        result = self.append_and_commit(self.entry(1))

        self.assertEqual(result[0], 1)
        self.assertEqual(self.verify(), result)

    def test_multiple_appends(self):
        self.append_and_commit(self.entry(1))
        result = self.append_and_commit(self.entry(2))

        self.assertEqual(result[0], 2)
        self.assertEqual(self.verify(), result)

    def test_append_requires_transaction(self):
        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(1),
            )

    def test_sequence_gap_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(2),
            )

        self.db.execute("ROLLBACK")
        self.assertEqual(self.verify()[0], 0)

    def test_duplicate_sequence_rejected(self):
        self.append_and_commit(self.entry(1))

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(1),
            )

        self.db.execute("ROLLBACK")
        self.assertEqual(self.verify()[0], 1)

    def test_wrong_stream_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(1, str(uuid.uuid4())),
            )

        self.db.execute("ROLLBACK")
        self.assertEqual(self.verify()[0], 0)

    def test_caller_rollback_removes_append(self):
        self.db.execute("BEGIN IMMEDIATE")

        append_history_entry(
            self.db,
            self.stream_id,
            self.entry(1),
        )

        self.db.execute("ROLLBACK")

        self.assertEqual(self.verify()[0], 0)

    def test_corrupted_commitment_blocks_append(self):
        self.append_and_commit(self.entry(1))

        self.db.execute(
            "UPDATE authorization_history_commitments "
            "SET digest=? WHERE history_sequence=1",
            ("0" * 64,),
        )

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(2),
            )

        self.db.execute("ROLLBACK")

    def test_missing_commitment_blocks_append(self):
        self.append_and_commit(self.entry(1))

        self.db.execute(
            "DELETE FROM authorization_history_commitments "
            "WHERE history_sequence=1"
        )

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                self.entry(2),
            )

        self.db.execute("ROLLBACK")

    def test_invalid_entry_rejected(self):
        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            append_history_entry(
                self.db,
                self.stream_id,
                object(),
            )

        self.db.execute("ROLLBACK")
        self.assertEqual(self.verify()[0], 0)


if __name__ == "__main__":
    unittest.main()


class AuthorizationHistoryAppendAtomicityTests(
    unittest.TestCase
):
    setUp = AuthorizationStatusHistoryAppendTests.setUp
    tearDown = AuthorizationStatusHistoryAppendTests.tearDown
    entry = AuthorizationStatusHistoryAppendTests.entry
    verify = AuthorizationStatusHistoryAppendTests.verify

    def test_commitment_insert_failure_rolls_back_entry(self):
        denied = []

        def authorizer(action, arg1, arg2, db_name, source):
            if (
                action == sqlite3.SQLITE_INSERT
                and arg1 == "authorization_history_commitments"
            ):
                denied.append(arg1)
                return sqlite3.SQLITE_DENY

            return sqlite3.SQLITE_OK

        self.db.execute("BEGIN IMMEDIATE")

        self.db.set_authorizer(authorizer)

        try:
            with self.assertRaises(sqlite3.DatabaseError):
                append_history_entry(
                    self.db,
                    self.stream_id,
                    self.entry(1),
                )
        finally:
            self.db.set_authorizer(None)

        self.assertTrue(denied)
        self.assertTrue(self.db.in_transaction)

        entry_count = self.db.execute(
            "SELECT COUNT(*) FROM authorization_history_entries"
        ).fetchone()[0]

        commitment_count = self.db.execute(
            "SELECT COUNT(*) FROM authorization_history_commitments"
        ).fetchone()[0]

        self.assertEqual(entry_count, 0)
        self.assertEqual(commitment_count, 0)

        self.db.execute("ROLLBACK")

        self.assertEqual(self.verify()[0], 0)

    def test_deferred_transaction_acquires_writer(self):
        self.db.execute("BEGIN")

        result = append_history_entry(
            self.db,
            self.stream_id,
            self.entry(1),
        )

        self.assertEqual(result[0], 1)
        self.assertEqual(
            verify_history_store(self.db, self.stream_id),
            result,
        )

        self.db.execute("ROLLBACK")

        self.assertEqual(self.verify()[0], 0)

    def test_failed_append_preserves_prior_transaction_work(self):
        self.db.execute("BEGIN IMMEDIATE")

        first = append_history_entry(
            self.db,
            self.stream_id,
            self.entry(1),
        )

        denied = []

        def authorizer(action, arg1, arg2, db_name, source):
            if (
                action == sqlite3.SQLITE_INSERT
                and arg1 == "authorization_history_commitments"
            ):
                denied.append(arg1)
                return sqlite3.SQLITE_DENY

            return sqlite3.SQLITE_OK

        self.db.set_authorizer(authorizer)

        try:
            with self.assertRaises(sqlite3.DatabaseError):
                append_history_entry(
                    self.db,
                    self.stream_id,
                    self.entry(2),
                )
        finally:
            self.db.set_authorizer(None)

        self.assertTrue(denied)
        self.assertTrue(self.db.in_transaction)

        entry_count = self.db.execute(
            "SELECT COUNT(*) FROM authorization_history_entries"
        ).fetchone()[0]

        commitment_count = self.db.execute(
            "SELECT COUNT(*) FROM authorization_history_commitments"
        ).fetchone()[0]

        self.assertEqual(entry_count, 1)
        self.assertEqual(commitment_count, 1)

        self.assertEqual(
            verify_history_store(self.db, self.stream_id),
            first,
        )

        self.db.execute("ROLLBACK")

        self.assertEqual(self.verify()[0], 0)
