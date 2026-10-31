"""A006 C2D-04B2B publication-intent persistence tests."""

import json
import sqlite3
import unittest
from uuid import uuid4

from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
    verify_publication_control,
)
from ariyan_trading.authorization_history_publication_intent import (
    create_publication_intent,
)
from ariyan_trading.authorization_history_publication_store import (
    record_publication_intent,
    verify_pending_publication_intent,
)
from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    verify_history_store,
)


class PublicationStoreTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:",
            isolation_level=None,
        )
        self.stream_id = str(uuid4())

        self.db.execute("BEGIN IMMEDIATE")

        initialize_history_store(
            self.db, self.stream_id
        )
        initialize_publication_control(self.db)

        self.db.commit()

        self.db.execute("BEGIN")
        sequence, digest = verify_history_store(
            self.db, self.stream_id
        )
        self.db.rollback()

        self.intent = create_publication_intent(
            self.stream_id, sequence, digest
        )

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def record(self):
        self.db.execute("BEGIN IMMEDIATE")
        result = record_publication_intent(
            self.db, self.intent
        )
        self.db.commit()
        return result

    def test_successful_persistence(self):
        result = self.record()

        self.assertEqual(
            result,
            (
                self.intent["history_sequence"],
                self.intent["history_digest"],
            ),
        )

        self.db.execute("BEGIN")

        self.assertEqual(
            verify_pending_publication_intent(
                self.db, self.stream_id
            ),
            self.intent,
        )

    def test_caller_rollback(self):
        self.db.execute("BEGIN IMMEDIATE")

        record_publication_intent(
            self.db, self.intent
        )

        self.db.rollback()

        self.db.execute("BEGIN")

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )

    def test_duplicate_intent_rejected(self):
        self.record()

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            record_publication_intent(
                self.db, self.intent
            )

        self.assertEqual(
            verify_pending_publication_intent(
                self.db, self.stream_id
            ),
            self.intent,
        )

    def test_wrong_digest_rejected(self):
        wrong = create_publication_intent(
            self.stream_id,
            self.intent["history_sequence"],
            "f" * 64,
        )

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            record_publication_intent(
                self.db, wrong
            )

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )

    def test_wrong_sequence_rejected(self):
        wrong = create_publication_intent(
            self.stream_id,
            self.intent["history_sequence"] + 1,
            self.intent["history_digest"],
        )

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaises(ValueError):
            record_publication_intent(
                self.db, wrong
            )

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )

    def test_record_requires_transaction(self):
        with self.assertRaises(ValueError):
            record_publication_intent(
                self.db, self.intent
            )

    def test_verify_requires_transaction(self):
        self.record()

        with self.assertRaises(ValueError):
            verify_pending_publication_intent(
                self.db, self.stream_id
            )

    def test_pending_rejected_by_ready_verifier(self):
        self.record()

        self.db.execute("BEGIN")

        with self.assertRaises(ValueError):
            verify_publication_control(self.db)

    def test_malformed_stored_json_rejected(self):
        self.record()

        self.db.execute(
            "UPDATE auth_pubctl_state "
            "SET value='not-json' "
            "WHERE key='publication_intent'"
        )

        self.db.execute("BEGIN")

        with self.assertRaises(ValueError):
            verify_pending_publication_intent(
                self.db, self.stream_id
            )

    def test_noncanonical_stored_json_rejected(self):
        self.record()

        noncanonical = json.dumps(
            self.intent,
            indent=2,
        )

        self.db.execute(
            "UPDATE auth_pubctl_state SET value=? "
            "WHERE key='publication_intent'",
            (noncanonical,),
        )

        self.db.execute("BEGIN")

        with self.assertRaises(ValueError):
            verify_pending_publication_intent(
                self.db, self.stream_id
            )

    def test_unexpected_metadata_rejected(self):
        self.record()

        self.db.execute(
            "INSERT INTO auth_pubctl_state "
            "(key,value) VALUES ('unexpected','value')"
        )

        self.db.execute("BEGIN")

        with self.assertRaises(ValueError):
            verify_pending_publication_intent(
                self.db, self.stream_id
            )

    def test_wrong_stream_rejected(self):
        self.record()

        self.db.execute("BEGIN")

        with self.assertRaises(ValueError):
            verify_pending_publication_intent(
                self.db, str(uuid4())
            )



    def _install_insert_failure(self):
        denied = []

        def authorizer(action, arg1, arg2, db_name, source):
            if (
                action == sqlite3.SQLITE_INSERT
                and arg1 == "auth_pubctl_state"
            ):
                denied.append((action, arg1))
                return sqlite3.SQLITE_DENY

            return sqlite3.SQLITE_OK

        self.db.set_authorizer(authorizer)
        return denied

    def test_insert_failure_restores_ready(self):
        self.db.execute("BEGIN IMMEDIATE")

        denied = self._install_insert_failure()

        try:
            with self.assertRaises(sqlite3.DatabaseError):
                record_publication_intent(
                    self.db, self.intent
                )
        finally:
            self.db.set_authorizer(None)

        self.assertEqual(
            denied,
            [(sqlite3.SQLITE_INSERT, "auth_pubctl_state")],
        )

        self.assertTrue(self.db.in_transaction)

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )

    def test_failure_preserves_prior_transaction_work(self):
        self.db.execute(
            "CREATE TABLE unrelated_work(value TEXT NOT NULL)"
        )

        self.db.execute("BEGIN IMMEDIATE")

        self.db.execute(
            "INSERT INTO unrelated_work(value) VALUES ('preserved')"
        )

        denied = self._install_insert_failure()

        try:
            with self.assertRaises(sqlite3.DatabaseError):
                record_publication_intent(
                    self.db, self.intent
                )
        finally:
            self.db.set_authorizer(None)

        self.assertEqual(
            denied,
            [(sqlite3.SQLITE_INSERT, "auth_pubctl_state")],
        )

        self.assertEqual(
            self.db.execute(
                "SELECT value FROM unrelated_work"
            ).fetchall(),
            [("preserved",)],
        )

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )


    def test_failure_after_pending_update_restores_ready(self):
        class InjectedFailureConnection:
            def __init__(self, connection):
                self.connection = connection
                self.saw_pending = False
                self.injected = False

            @property
            def in_transaction(self):
                return self.connection.in_transaction

            def execute(self, sql, parameters=()):
                if (
                    sql.startswith(
                        "INSERT INTO auth_pubctl_state"
                    )
                    and parameters
                    and parameters[0] == "publication_intent"
                ):
                    state = self.connection.execute(
                        "SELECT value FROM auth_pubctl_state "
                        "WHERE key='publication_state'"
                    ).fetchone()

                    self.saw_pending = state == ("PENDING",)
                    self.injected = True

                    raise sqlite3.OperationalError(
                        "Injected failure after state update"
                    )

                return self.connection.execute(
                    sql, parameters
                )

            def __getattr__(self, name):
                return getattr(self.connection, name)

        proxy = InjectedFailureConnection(self.db)

        self.db.execute("BEGIN IMMEDIATE")

        with self.assertRaisesRegex(
            sqlite3.OperationalError,
            "Injected failure after state update",
        ):
            record_publication_intent(
                proxy, self.intent
            )

        self.assertTrue(proxy.injected)
        self.assertTrue(proxy.saw_pending)
        self.assertTrue(self.db.in_transaction)

        self.assertEqual(
            verify_publication_control(self.db),
            "READY",
        )

        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM auth_pubctl_state "
                "WHERE key='publication_intent'"
            ).fetchone()[0],
            0,
        )


    def test_second_writer_blocked_until_first_finishes(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            database_path = str(
                Path(directory) / "publication-test.sqlite"
            )

            first = sqlite3.connect(
                database_path,
                isolation_level=None,
                timeout=0.1,
            )

            second = sqlite3.connect(
                database_path,
                isolation_level=None,
                timeout=0.1,
            )

            try:
                first.execute("BEGIN IMMEDIATE")

                initialize_history_store(
                    first, self.stream_id
                )
                initialize_publication_control(first)
                first.commit()

                first.execute("BEGIN IMMEDIATE")

                record_publication_intent(
                    first, self.intent
                )

                second.execute("BEGIN")

                with self.assertRaises(sqlite3.OperationalError):
                    record_publication_intent(
                        second, self.intent
                    )

                second.rollback()
                first.commit()

                second.execute("BEGIN IMMEDIATE")

                with self.assertRaises(ValueError):
                    record_publication_intent(
                        second, self.intent
                    )

                self.assertEqual(
                    verify_pending_publication_intent(
                        second, self.stream_id
                    ),
                    self.intent,
                )

                second.rollback()

            finally:
                if first.in_transaction:
                    first.rollback()

                if second.in_transaction:
                    second.rollback()

                first.close()
                second.close()


if __name__ == "__main__":
    unittest.main()
