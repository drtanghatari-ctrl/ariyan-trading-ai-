"""A006: persisted publication uncertainty blocks authentication."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class PendingPublicationA006Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.key = b"Pending-publication-test-key-only!"
        self.ledger = DurableLedger(
            self.database, opening_cash="1000.00"
        )
        self.addCleanup(self.ledger.close)

        db = self.ledger.db
        db.execute("BEGIN")
        try:
            self.digest = verify_protected_journal(
                db, self.ledger.opening_cash
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        write_anchor(
            self.anchor,
            create_anchor(0, self.digest, self.key),
            self.key,
        )

    def mark_pending(self, value):
        self.ledger.db.execute(
            "INSERT INTO ledger_meta(key,value) VALUES (?,?)",
            ("checkpoint_publication_pending", value),
        )

    def test_pending_blocks_even_matching_authenticated_anchor(self):
        original_anchor = self.anchor.read_bytes()
        self.mark_pending("attempt-001")
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            with self.assertRaisesRegex(ValueError, "pending or uncertain"):
                verify_checkpoint(
                    db, self.ledger.opening_cash,
                    self.anchor, self.key,
                )
        finally:
            db.rollback()
        self.assertEqual(self.anchor.read_bytes(), original_anchor)
        self.assertEqual(
            db.execute(
                "SELECT value FROM ledger_meta "
                "WHERE key='checkpoint_publication_pending'"
            ).fetchone(),
            ("attempt-001",),
        )

    def test_pending_survives_reopen_and_blocks_verified_open(self):
        self.mark_pending("attempt-002")
        with self.assertRaisesRegex(ValueError, "pending or uncertain"):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=self.key,
            )

    def test_empty_marker_cannot_bypass_guard(self):
        self.mark_pending("")
        with self.assertRaisesRegex(ValueError, "pending or uncertain"):
            DurableLedger(
                self.database,
                checkpoint_path=self.anchor,
                checkpoint_key=self.key,
            )


if __name__ == "__main__":
    unittest.main()
