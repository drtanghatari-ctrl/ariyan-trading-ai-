"""A006 C2C4: authorization-history writer contention tests."""

import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

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


def make_entry(stream_id, sequence):
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
        stream_id=stream_id,
        history_sequence=sequence,
        observation=observation,
    )


class AuthorizationHistoryConcurrencyTests(unittest.TestCase):

    def test_competing_connections_delete_and_wal(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(journal_mode=mode):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "history.sqlite"
                    stream_id = str(uuid.uuid4())

                    a = sqlite3.connect(
                        str(path),
                        isolation_level=None,
                        timeout=0.2,
                    )
                    b = sqlite3.connect(
                        str(path),
                        isolation_level=None,
                        timeout=0.2,
                    )

                    try:
                        actual_mode = a.execute(
                            f"PRAGMA journal_mode={mode}"
                        ).fetchone()[0]

                        self.assertEqual(
                            actual_mode.upper(),
                            mode,
                        )

                        a.execute("BEGIN IMMEDIATE")
                        initialize_history_store(a, stream_id)
                        a.execute("COMMIT")

                        first = make_entry(stream_id, 1)
                        second = make_entry(stream_id, 2)

                        a.execute("BEGIN IMMEDIATE")
                        append_history_entry(
                            a, stream_id, first
                        )

                        b.execute("BEGIN")

                        with self.assertRaises(
                            sqlite3.OperationalError
                        ) as blocked:
                            append_history_entry(
                                b, stream_id, first
                            )

                        self.assertIn(
                            blocked.exception.sqlite_errorcode,
                            (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED),
                        )

                        b.execute("ROLLBACK")
                        a.execute("COMMIT")

                        b.execute("BEGIN IMMEDIATE")

                        with self.assertRaises(ValueError):
                            append_history_entry(
                                b, stream_id, first
                            )

                        b.execute("ROLLBACK")

                        b.execute("BEGIN IMMEDIATE")

                        result = append_history_entry(
                            b, stream_id, second
                        )

                        b.execute("COMMIT")

                        a.execute("BEGIN")

                        verified = verify_history_store(
                            a, stream_id
                        )

                        a.execute("ROLLBACK")

                        self.assertEqual(result, verified)
                        self.assertEqual(verified[0], 2)

                    finally:
                        for db in (a, b):
                            if db.in_transaction:
                                db.execute("ROLLBACK")
                            db.close()


if __name__ == "__main__":
    unittest.main()
