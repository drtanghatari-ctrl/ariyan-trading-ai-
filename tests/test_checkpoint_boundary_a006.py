"""A006 authenticated checkpoint boundary tests."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.trust_anchor import (
    create_anchor,
    write_anchor,
)
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.checkpoint_state import classify_checkpoint


class CheckpointBoundaryA006Tests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.anchor = root / "checkpoint.json"
        self.key = b"A" * 32
        self.ledger = DurableLedger(
            root / "ledger.sqlite",
            opening_cash="1000.00",
        )
        self.addCleanup(self.ledger.close)
        self.ledger.db.execute("BEGIN")
        self.addCleanup(
            lambda: self.ledger.db.rollback()
            if self.ledger.db.in_transaction else None
        )

    def tip(self):
        digest = verify_protected_journal(
            self.ledger.db,
            self.ledger.opening_cash,
        )
        count = self.ledger.db.execute(
            "SELECT COUNT(*) FROM ledger_entries"
        ).fetchone()[0]
        return count, digest

    def publish(self, sequence, digest):
        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, self.key),
            self.key,
        )

    def verify(self, key=None):
        return verify_checkpoint(
            self.ledger.db,
            self.ledger.opening_cash,
            self.anchor,
            self.key if key is None else key,
        )

    def test_classifier_flag_cannot_bypass_missing_anchor(self):
        sequence, digest = self.tip()
        decision = classify_checkpoint(
            journal_sequence=sequence,
            journal_digest=digest,
            anchor_sequence=sequence,
            anchor_digest=digest,
            anchor_authenticated=True,
        )
        self.assertTrue(decision.verification_eligible)
        with self.assertRaises(FileNotFoundError):
            self.verify()
        self.assertFalse(self.anchor.exists())

    def test_wrong_key_rejected(self):
        sequence, digest = self.tip()
        self.publish(sequence, digest)
        with self.assertRaises(ValueError):
            self.verify(key=b"B" * 32)

    def test_stale_anchor_rejected(self):
        sequence, digest = self.tip()
        self.publish(sequence, digest)
        self.ledger.db.rollback()
        self.ledger.record_buy("test", "1", "10")
        self.ledger.db.execute("BEGIN")
        with self.assertRaisesRegex(
            ValueError, "Checkpoint sequence mismatch"
        ):
            self.verify()

    def test_successful_verification_does_not_modify_anchor(self):
        sequence, digest = self.tip()
        self.publish(sequence, digest)
        before = self.anchor.read_bytes()
        self.assertEqual(self.verify(), (sequence, digest))
        self.assertEqual(self.anchor.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
