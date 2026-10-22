"""A006: opt-in authenticated verification on ledger opening."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.ariyan_trading.durable_ledger import DurableLedger
from app.ariyan_trading.journal_store import verify_protected_journal
from app.ariyan_trading.trust_anchor import create_anchor, write_anchor


KEY = b"A006-test-key-not-for-production-use-123456"
WRONG_KEY = b"A006-wrong-key-not-for-production-123456"


class CheckpointOpeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "checkpoint.json"

    def create_ledger(self):
        ledger = DurableLedger(self.database, opening_cash="1000")
        ledger.db.close()

    def publish_checkpoint(self, sequence_override=None):
        ledger = DurableLedger(self.database)
        try:
            ledger.db.execute("BEGIN")
            digest = verify_protected_journal(
                ledger.db, ledger.opening_cash
            )
            sequence = ledger.db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            ledger.db.execute("COMMIT")
        finally:
            ledger.db.close()

        if sequence_override is not None:
            sequence = sequence_override

        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, KEY),
            KEY,
        )

    def test_valid_checkpoint_opens(self):
        self.create_ledger()
        self.publish_checkpoint()
        ledger = DurableLedger(
            self.database,
            checkpoint_path=self.anchor,
            checkpoint_key=KEY,
        )
        try:
            self.assertEqual(ledger.balances()[0], Decimal("1000.00"))
        finally:
            ledger.db.close()

    def test_missing_checkpoint_rejected(self):
        self.create_ledger()
        with self.assertRaises(FileNotFoundError):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )

    def test_wrong_key_rejected(self):
        self.create_ledger()
        self.publish_checkpoint()
        with self.assertRaises(ValueError):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=WRONG_KEY,
            )

    def test_stale_sequence_rejected(self):
        self.create_ledger()
        self.publish_checkpoint(sequence_override=1)
        with self.assertRaisesRegex(ValueError, "sequence mismatch"):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )

    def test_partial_configuration_rejected(self):
        self.create_ledger()
        with self.assertRaises(ValueError):
            DurableLedger(self.database, checkpoint_path=self.anchor)
        with self.assertRaises(ValueError):
            DurableLedger(self.database, checkpoint_key=KEY)

    def test_existing_legacy_open_unchanged(self):
        self.create_ledger()
        ledger = DurableLedger(self.database)
        try:
            self.assertEqual(ledger.balances()[0], Decimal("1000.00"))
        finally:
            ledger.db.close()

    def test_new_ledger_with_checkpoint_rejected(self):
        with self.assertRaises(ValueError):
            DurableLedger(
                self.database,
                opening_cash="1000",
                checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )


    def test_authenticated_digest_mismatch(self):
        self.create_ledger()
        self.publish_checkpoint()

        wrong_digest = "0" * 64
        write_anchor(
            self.anchor,
            create_anchor(0, wrong_digest, KEY),
            KEY,
        )

        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )

    def test_checkpoint_rejects_later_trade(self):
        self.create_ledger()
        self.publish_checkpoint()

        ledger = DurableLedger(self.database)
        try:
            ledger.record_buy("trade-after-anchor", "1", "10")
        finally:
            ledger.db.close()

        with self.assertRaisesRegex(ValueError, "sequence mismatch"):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=KEY,
            )


    def test_verified_session_rejects_trades(self):
        self.create_ledger()
        self.publish_checkpoint()

        ledger = DurableLedger(
            self.database,
            checkpoint_path=self.anchor,
            checkpoint_key=KEY,
        )
        try:
            with self.assertRaisesRegex(
                RuntimeError, "read-only"
            ):
                ledger.record_buy("blocked-buy", "1", "10")

            with self.assertRaisesRegex(
                RuntimeError, "read-only"
            ):
                ledger.record_sell("blocked-sell", "1", "10")

            count = ledger.db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            self.assertEqual(count, 0)
        finally:
            ledger.db.close()


if __name__ == "__main__":
    unittest.main()
