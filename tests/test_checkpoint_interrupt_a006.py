"""A006 simulated checkpoint publication interruptions.

Uses temporary SQLite databases and authenticated anchor files.
Does not implement automatic publication or recovery.
"""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointInterruptA006Tests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.key = b"A" * 32
        self.ledger = DurableLedger(
            self.database,
            opening_cash="1000.00",
        )
        self.addCleanup(self.ledger.close)
        self.publish_current_tip()

    def tip(self):
        db = self.ledger.db
        digest = verify_protected_journal(
            db, self.ledger.opening_cash
        )
        sequence = db.execute(
            "SELECT COUNT(*) FROM ledger_entries"
        ).fetchone()[0]
        return sequence, digest

    def publish_current_tip(self):
        sequence, digest = self.tip()
        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, self.key),
            self.key,
        )

    def verify(self):
        return verify_checkpoint(
            self.ledger.db,
            self.ledger.opening_cash,
            self.anchor,
            self.key,
        )

    def test_interruption_before_commit_preserves_checkpoint(self):
        initial_tip = self.tip()
        initial_anchor = self.anchor.read_bytes()
        db = self.ledger.db

        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "INSERT INTO ledger_entries "
                "(request_id,action,quantity,price,"
                "cash_delta,units_delta) "
                "VALUES (?,?,?,?,?,?)",
                ("interrupted", "BUY", "1", "10", "-10", "1"),
            )
            uncommitted_count = db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            self.assertEqual(
                uncommitted_count, initial_tip[0] + 1
            )
        except Exception:
            db.rollback()
            raise
        else:
            # Simulate interruption before transaction commit.
            db.rollback()

        self.assertEqual(self.tip(), initial_tip)
        self.assertEqual(self.anchor.read_bytes(), initial_anchor)

        db.execute("BEGIN")
        try:
            self.assertEqual(self.verify(), initial_tip)
        finally:
            db.rollback()

    def test_interruption_after_commit_rejects_old_anchor(self):
        initial_tip = self.tip()
        initial_anchor = self.anchor.read_bytes()

        # DurableLedger commits the protected journal transaction.
        self.ledger.record_buy("committed", "1", "10")
        committed_tip = self.tip()

        self.assertEqual(
            committed_tip[0], initial_tip[0] + 1
        )
        self.assertNotEqual(committed_tip, initial_tip)

        # Simulated interruption: no anchor publication follows.
        self.assertEqual(
            self.anchor.read_bytes(), initial_anchor
        )

        self.ledger.db.execute("BEGIN")
        try:
            with self.assertRaisesRegex(
                ValueError, "Checkpoint sequence mismatch"
            ):
                self.verify()
        finally:
            self.ledger.db.rollback()

        # Verification must not repair or alter either side.
        self.assertEqual(self.tip(), committed_tip)
        self.assertEqual(
            self.anchor.read_bytes(), initial_anchor
        )


if __name__ == "__main__":
    unittest.main()
