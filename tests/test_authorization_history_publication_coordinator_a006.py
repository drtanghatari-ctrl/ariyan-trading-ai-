"""A006 C2D-04B2C3B publication coordinator tests."""

import os
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_anchor_io import (
    read_history_anchor,
    write_history_anchor,
)
from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
    verify_publication_control,
)
from ariyan_trading.authorization_history_publication_coordinator import (
    HistoryPublicationUncertain,
    publish_prepared_history,
)
from ariyan_trading.authorization_history_prepare_coordinator import (
    prepare_history_publication,
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


class FaultConnection:
    def __init__(self, db, failure):
        self.db = db
        self.failure = failure

    def __getattr__(self, name):
        return getattr(self.db, name)

    def execute(self, sql, *args):
        if self.failure == "delete" and sql.startswith(
            "DELETE FROM auth_pubctl_state"
        ):
            raise RuntimeError("Injected marker deletion failure")

        if self.failure == "commit" and sql == "COMMIT":
            raise RuntimeError("Injected final commit failure")

        return self.db.execute(sql, *args)


class HistoryPublicationTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)

        root = Path(temp.name)
        self.anchor_path = root / "history-anchor.json"

        self.db = sqlite3.connect(
            root / "history.sqlite",
            isolation_level=None,
        )
        self.addCleanup(self.db.close)

        self.db.execute("PRAGMA synchronous=FULL")

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

        self.predecessor = create_history_anchor(
            self.stream_id, sequence, digest, self.key
        )

        write_history_anchor(
            self.anchor_path, self.predecessor, self.key
        )

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
            sequence=1,
            observed_at=101,
            valid_until=201,
        )

        entry = AuthorizationStatusHistoryEntry(
            version=HISTORY_VERSION,
            stream_id=self.stream_id,
            history_sequence=1,
            observation=observation,
        )

        self.prepared = prepare_history_publication(
            self.db,
            self.stream_id,
            entry,
            self.predecessor,
            self.key,
        )

    def publish(self, db=None):
        return publish_prepared_history(
            self.db if db is None else db,
            self.stream_id,
            self.predecessor,
            self.anchor_path,
            self.key,
        )

    def pending(self):
        self.db.execute("BEGIN")
        try:
            return verify_pending_publication_intent(
                self.db, self.stream_id
            )
        finally:
            self.db.rollback()

    def test_successful_publication(self):
        result = self.publish()

        self.assertEqual(result["state"], "DURABLE")
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(
            result["digest"], self.prepared["digest"]
        )

        self.assertEqual(
            read_history_anchor(self.anchor_path, self.key),
            (
                self.stream_id,
                1,
                self.prepared["digest"],
            ),
        )

        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                verify_publication_control(self.db),
                "READY",
            )
        finally:
            self.db.rollback()

    def test_second_publication_rejected(self):
        self.publish()

        with self.assertRaises(ValueError):
            self.publish()

    def test_missing_anchor_rejected_before_publication(self):
        self.anchor_path.unlink()

        with self.assertRaises(FileNotFoundError):
            self.publish()

        self.assertEqual(
            self.pending()["history_sequence"], 1
        )

    def test_directory_fsync_failure_is_uncertain(self):
        real_fsync = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("Injected directory fsync failure")
            return real_fsync(fd)

        with patch(
            "ariyan_trading.authorization_history_anchor_io.os.fsync",
            side_effect=fail_directory,
        ):
            with self.assertRaises(
                HistoryPublicationUncertain
            ):
                self.publish()

        self.assertEqual(
            read_history_anchor(self.anchor_path, self.key)[1],
            1,
        )
        self.assertEqual(
            self.pending()["history_sequence"], 1
        )

    def test_marker_deletion_failure_is_uncertain(self):
        proxy = FaultConnection(self.db, "delete")

        with self.assertRaises(
            HistoryPublicationUncertain
        ):
            self.publish(db=proxy)

        self.assertEqual(
            self.pending()["history_sequence"], 1
        )
        self.assertEqual(
            read_history_anchor(self.anchor_path, self.key)[1],
            1,
        )

    def test_final_commit_failure_is_uncertain(self):
        proxy = FaultConnection(self.db, "commit")

        with self.assertRaises(
            HistoryPublicationUncertain
        ):
            self.publish(db=proxy)

        self.assertEqual(
            self.pending()["history_sequence"], 1
        )
        self.assertEqual(
            read_history_anchor(self.anchor_path, self.key)[1],
            1,
        )

    def test_requires_idle_connection(self):
        self.db.execute("BEGIN")

        try:
            with self.assertRaises(ValueError):
                self.publish()
        finally:
            self.db.rollback()

    def test_requires_full_synchronous(self):
        self.db.execute("PRAGMA synchronous=NORMAL")

        with self.assertRaises(ValueError):
            self.publish()

        self.assertEqual(
            self.pending()["history_sequence"], 1
        )


    def test_commit_succeeds_but_confirmation_fails(self):
        class AmbiguousCommitConnection:
            def __init__(self, db):
                self.db = db

            def __getattr__(self, name):
                return getattr(self.db, name)

            def execute(self, sql, *args):
                result = self.db.execute(sql, *args)

                if sql == "COMMIT":
                    raise OSError(
                        "Injected lost commit confirmation"
                    )

                return result

        proxy = AmbiguousCommitConnection(self.db)

        with self.assertRaises(
            HistoryPublicationUncertain
        ):
            self.publish(db=proxy)

        self.assertFalse(self.db.in_transaction)

        self.assertEqual(
            read_history_anchor(self.anchor_path, self.key),
            (
                self.stream_id,
                1,
                self.prepared["digest"],
            ),
        )

        self.db.execute("BEGIN")
        try:
            self.assertEqual(
                verify_publication_control(self.db),
                "READY",
            )
        finally:
            self.db.rollback()

        # The original predecessor is no longer the disk tip.
        # The coordinator must not publish it again.
        with self.assertRaises(ValueError):
            self.publish()

    def test_retry_after_directory_sync_failure_rejected(self):
        real_fsync = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(
                    "Injected directory synchronization failure"
                )
            return real_fsync(fd)

        with patch(
            "ariyan_trading.authorization_history_anchor_io.os.fsync",
            side_effect=fail_directory,
        ):
            with self.assertRaises(
                HistoryPublicationUncertain
            ):
                self.publish()

        before = self.anchor_path.read_bytes()

        # The disk anchor now contains sequence 1, while
        # the trusted predecessor is sequence 0.
        # The pending intent remains in SQLite.
        with self.assertRaises(ValueError):
            self.publish()

        self.assertEqual(
            self.anchor_path.read_bytes(),
            before,
        )

        self.assertEqual(
            self.pending()["history_sequence"],
            1,
        )


    def test_database_path_collision_rejected(self):
        database_path = Path(
            self.db.execute("PRAGMA database_list").fetchone()[2]
        )

        with self.assertRaises(ValueError):
            publish_prepared_history(
                self.db,
                self.stream_id,
                self.predecessor,
                database_path,
                self.key,
            )

        self.assertEqual(
            self.pending()["history_sequence"],
            1,
        )

    def test_sqlite_companion_paths_rejected(self):
        database_path = Path(
            self.db.execute("PRAGMA database_list").fetchone()[2]
        )

        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                with self.assertRaises(ValueError):
                    publish_prepared_history(
                        self.db,
                        self.stream_id,
                        self.predecessor,
                        str(database_path) + suffix,
                        self.key,
                    )

    def test_database_symlink_alias_rejected(self):
        database_path = Path(
            self.db.execute("PRAGMA database_list").fetchone()[2]
        )

        alias = database_path.parent / "database-alias.json"
        alias.symlink_to(database_path)

        with self.assertRaises(ValueError):
            publish_prepared_history(
                self.db,
                self.stream_id,
                self.predecessor,
                alias,
                self.key,
            )

    def test_in_memory_database_rejected(self):
        memory_db = sqlite3.connect(":memory:")

        try:
            with self.assertRaises(ValueError):
                from ariyan_trading.authorization_history_publication_path_guard import (
                    verify_history_anchor_path,
                )

                verify_history_anchor_path(
                    memory_db,
                    self.anchor_path,
                )
        finally:
            memory_db.close()


if __name__ == "__main__":
    unittest.main()
