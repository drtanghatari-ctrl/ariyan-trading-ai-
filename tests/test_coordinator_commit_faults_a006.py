"""A006 modeled SQLite API failures at commit and marker clearance."""

import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.checkpoint_coordinator import (
    PENDING, PublicationUncertain, execute_checkpointed_trade,
)
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, read_anchor, write_anchor

KEY = b"A006-commit-fault-test-key-only!!"


class FaultConnection:
    def __init__(self, db, commit_number=None, after=False, clear=False):
        self.db = db
        self.commit_number = commit_number
        self.after = after
        self.clear = clear
        self.commits = 0

    def __getattr__(self, name):
        return getattr(self.db, name)

    def execute(self, sql, *args):
        if self.clear and sql.startswith("DELETE FROM ledger_meta"):
            raise sqlite3.OperationalError("injected marker clearance failure")
        if sql.strip().upper() == "COMMIT":
            self.commits += 1
            if self.commits == self.commit_number:
                if self.after:
                    self.db.execute(sql, *args)
                raise sqlite3.OperationalError("injected commit outcome")
        return self.db.execute(sql, *args)


class CoordinatorCommitFaultA006Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.ledger = DurableLedger(
            self.database, opening_cash="1000.00"
        )
        self.addCleanup(self.ledger.close)
        db = self.ledger.db
        db.execute("BEGIN")
        digest = verify_protected_journal(db, self.ledger.opening_cash)
        db.commit()
        write_anchor(self.anchor, create_anchor(0, digest, KEY), KEY)

    def run_fault(self, *, commit_number=None, after=False, clear=False):
        self.ledger.db = FaultConnection(
            self.ledger.db, commit_number, after, clear
        )
        with self.assertRaises(PublicationUncertain):
            execute_checkpointed_trade(
                self.ledger, "BUY", "fault-request", "1", "10.00",
                anchor_path=self.anchor, key=KEY,
            )
        self.assertFalse(self.ledger.db.in_transaction)

    def inspect(self):
        db = sqlite3.connect(self.database)
        try:
            self.assertEqual(
                db.execute("PRAGMA integrity_check").fetchall(), [("ok",)]
            )
            count = db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            pending = db.execute(
                "SELECT value FROM ledger_meta WHERE key=?", (PENDING,)
            ).fetchone()
            return count, pending
        finally:
            db.close()

    def assert_pending_blocks_restart(self):
        self.assertIsNotNone(self.inspect()[1])
        with self.assertRaisesRegex(ValueError, "pending or uncertain"):
            DurableLedger(
                self.database, checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )

    def test_trade_commit_error_before_application_rolls_back(self):
        before = self.anchor.read_bytes()
        self.run_fault(commit_number=1)
        self.assertEqual(self.inspect(), (0, None))
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(self.ledger.balances()[0], Decimal("1000.00"))

    def test_trade_commit_error_after_application_preserves_pending(self):
        before = self.anchor.read_bytes()
        self.run_fault(commit_number=1, after=True)
        self.assertEqual(self.inspect()[0], 1)
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assert_pending_blocks_restart()

    def test_clearance_commit_error_before_application_keeps_pending(self):
        self.run_fault(commit_number=2)
        self.assertEqual(self.inspect()[0], 1)
        self.assertEqual(read_anchor(self.anchor, KEY)[0], 1)
        self.assert_pending_blocks_restart()

    def test_clearance_commit_error_after_application_is_not_reexecuted(self):
        self.run_fault(commit_number=2, after=True)
        self.assertEqual(self.inspect(), (1, None))
        reader = DurableLedger(
            self.database, checkpoint_path=self.anchor,
            checkpoint_key=KEY,
        )
        try:
            self.assertEqual(reader.balances()[0], Decimal("990.00"))
        finally:
            reader.close()

        with self.assertRaises(sqlite3.IntegrityError):
            execute_checkpointed_trade(
                self.ledger, "BUY", "fault-request", "1", "10.00",
                anchor_path=self.anchor, key=KEY,
            )
        self.assertEqual(self.inspect(), (1, None))

    def test_marker_delete_failure_keeps_committed_pending_evidence(self):
        self.run_fault(clear=True)
        self.assertEqual(self.inspect()[0], 1)
        self.assertEqual(read_anchor(self.anchor, KEY)[0], 1)
        self.assert_pending_blocks_restart()


if __name__ == "__main__":
    unittest.main()
