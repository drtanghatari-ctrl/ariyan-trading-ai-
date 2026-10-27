"""A006-WB02-P3B authenticated enrollment verifier tests."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.enrollment_verifier import verify_enrollment
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor
from ariyan_trading.writer_policy import create_writer_policy


KEY = b"A006-P3B-disposable-test-key-1234567890"


class EnrollmentVerifierTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        root = Path(self.temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "checkpoint.json"

        self.ledger = DurableLedger(
            self.database, opening_cash="1000.00"
        )
        self.addCleanup(self.ledger.close)

    def checkpoint(self):
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            digest = verify_protected_journal(
                db, self.ledger.opening_cash
            )
            sequence = db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, KEY),
            KEY,
        )
        return sequence, digest

    def policy(self, sequence, digest, identity=None):
        return create_writer_policy(
            identity or self.ledger.ledger_identity,
            sequence,
            digest,
            KEY,
        )

    def verify(self, policy):
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            return verify_enrollment(
                db,
                self.ledger.opening_cash,
                self.anchor,
                KEY,
                policy,
                KEY,
            )
        finally:
            db.rollback()

    def test_valid_genesis_enrollment(self):
        sequence, digest = self.checkpoint()
        result = self.verify(self.policy(sequence, digest))
        self.assertEqual(result["enrollment_sequence"], 0)

    def test_valid_historical_enrollment(self):
        self.ledger.record_buy("buy-1", "1", "10")
        sequence, digest = self.checkpoint()
        policy = self.policy(sequence, digest)

        self.ledger.record_sell("sell-1", "1", "11")
        self.checkpoint()

        result = self.verify(policy)
        self.assertEqual(result["enrollment_sequence"], 1)

    def test_wrong_identity_rejected(self):
        import uuid

        sequence, digest = self.checkpoint()
        policy = self.policy(
            sequence, digest, str(uuid.uuid4())
        )

        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.verify(policy)

    def test_future_sequence_rejected(self):
        _, digest = self.checkpoint()
        policy = self.policy(10, digest)

        with self.assertRaisesRegex(ValueError, "exceeds journal tip"):
            self.verify(policy)

    def test_wrong_historical_digest_rejected(self):
        sequence, _ = self.checkpoint()
        policy = self.policy(sequence, "ab" * 32)

        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.verify(policy)

    def test_modified_policy_rejected(self):
        sequence, digest = self.checkpoint()
        policy = self.policy(sequence, digest)
        policy["enrollment_sequence"] = 5

        with self.assertRaises(ValueError):
            self.verify(policy)

    def test_stale_checkpoint_rejected(self):
        sequence, digest = self.checkpoint()
        policy = self.policy(sequence, digest)

        self.ledger.record_buy("buy-after-anchor", "1", "10")

        with self.assertRaises(ValueError):
            self.verify(policy)

    def test_missing_ledger_identity_rejected(self):
        sequence, digest = self.checkpoint()
        policy = self.policy(sequence, digest)

        self.ledger.db.execute(
            "DELETE FROM ledger_meta WHERE key='ledger_identity'"
        )

        with self.assertRaisesRegex(ValueError, "identity missing"):
            self.verify(policy)

    def test_transaction_required(self):
        sequence, digest = self.checkpoint()
        policy = self.policy(sequence, digest)

        with self.assertRaisesRegex(ValueError, "Active transaction"):
            verify_enrollment(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor,
                KEY,
                policy,
                KEY,
            )


if __name__ == "__main__":
    unittest.main()
