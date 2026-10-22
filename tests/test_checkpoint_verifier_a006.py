"""A006 checkpoint verification against a real temporary ledger."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointVerifierA006Tests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        directory = Path(self.temp.name)
        self.anchor_path = directory / "checkpoint.json"
        self.key = b"A" * 32

        self.ledger = DurableLedger(
            directory / "ledger.sqlite",
            opening_cash="1000.00",
        )
        self.addCleanup(self.ledger.close)

        self.ledger.db.execute("BEGIN")
        self.addCleanup(
            lambda: self.ledger.db.rollback()
            if self.ledger.db.in_transaction else None
        )

    def journal_tip(self):
        digest = verify_protected_journal(
            self.ledger.db,
            self.ledger.opening_cash,
        )
        sequence = self.ledger.db.execute(
            "SELECT COUNT(*) FROM ledger_entries"
        ).fetchone()[0]
        return sequence, digest

    def publish(self, sequence, digest):
        anchor = create_anchor(sequence, digest, self.key)
        write_anchor(self.anchor_path, anchor, self.key)

    def test_valid_checkpoint_accepted(self):
        sequence, digest = self.journal_tip()
        self.publish(sequence, digest)

        self.assertEqual(
            verify_checkpoint(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor_path,
                self.key,
            ),
            (sequence, digest),
        )

    def test_missing_checkpoint_rejected(self):
        with self.assertRaises(FileNotFoundError):
            verify_checkpoint(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor_path,
                self.key,
            )

    def test_authenticated_wrong_digest_rejected(self):
        sequence, digest = self.journal_tip()
        wrong = "ab" * 32
        self.assertNotEqual(wrong, digest)
        self.publish(sequence, wrong)

        with self.assertRaisesRegex(
            ValueError, "Checkpoint digest mismatch"
        ):
            verify_checkpoint(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor_path,
                self.key,
            )

    def test_authenticated_wrong_sequence_rejected(self):
        sequence, digest = self.journal_tip()
        self.publish(sequence + 1, digest)

        with self.assertRaisesRegex(
            ValueError, "Checkpoint sequence mismatch"
        ):
            verify_checkpoint(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor_path,
                self.key,
            )


if __name__ == "__main__":
    unittest.main()
