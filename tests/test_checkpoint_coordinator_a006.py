"""A006 paper coordinator integration and publication failures."""

import os
import stat
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.checkpoint_coordinator import (
    PENDING, PublicationUncertain, execute_checkpointed_trade,
)
from ariyan_trading.checkpoint_publication import PublicationState
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, read_anchor, write_anchor


class CoordinatorA006Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.key = b"Coordinator-test-key-not-production!"
        self.ledger = DurableLedger(
            self.database, opening_cash="1000.00"
        )
        self.addCleanup(self.ledger.close)
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            digest = verify_protected_journal(
                db, self.ledger.opening_cash
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        write_anchor(
            self.anchor, create_anchor(0, digest, self.key), self.key
        )

    def trade(self, request="buy-1", action="BUY", quantity="1"):
        return execute_checkpointed_trade(
            self.ledger, action, request, quantity, "10.00",
            anchor_path=self.anchor, key=self.key,
        )

    def pending(self):
        return self.ledger.db.execute(
            "SELECT value FROM ledger_meta WHERE key=?", (PENDING,)
        ).fetchone()

    def test_buy_sell_and_verified_restart(self):
        buy = self.trade()
        self.assertIs(buy["state"], PublicationState.DURABLE)
        self.assertEqual(buy["cash"], Decimal("990.00"))
        sell = self.trade("sell-1", "SELL")
        self.assertEqual(sell["sequence"], 2)
        self.assertEqual(sell["cash"], Decimal("1000.00"))
        self.assertIsNone(self.pending())
        reader = DurableLedger(
            self.database, checkpoint_path=self.anchor,
            checkpoint_key=self.key,
        )
        try:
            self.assertEqual(
                reader.balances(), (Decimal("1000.00"), Decimal("0"))
            )
        finally:
            reader.close()

    def test_rejected_trade_changes_neither_journal_nor_anchor(self):
        before = self.anchor.read_bytes()
        with self.assertRaisesRegex(ValueError, "Insufficient cash"):
            self.trade(quantity="101")
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(self.ledger.balances()[0], Decimal("1000.00"))
        self.assertIsNone(self.pending())

    def test_duplicate_request_cannot_execute_twice(self):
        self.trade()
        before = self.anchor.read_bytes()
        with self.assertRaises(Exception):
            self.trade()
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(self.ledger.balances()[0], Decimal("990.00"))
        self.assertIsNone(self.pending())

    def test_missing_anchor_cannot_be_enrolled_automatically(self):
        self.anchor.unlink()
        with self.assertRaises(FileNotFoundError):
            self.trade()
        self.assertFalse(self.anchor.exists())
        self.assertEqual(self.ledger.balances()[0], Decimal("1000.00"))
        self.assertIsNone(self.pending())

    def test_replace_failure_preserves_trade_and_blocks_restart(self):
        before = self.anchor.read_bytes()
        with patch(
            "ariyan_trading.trust_anchor.os.replace",
            side_effect=OSError("replace failed"),
        ):
            with self.assertRaises(PublicationUncertain):
                self.trade()
        self.assertEqual(self.anchor.read_bytes(), before)
        self.assertEqual(self.ledger.balances()[0], Decimal("990.00"))
        self.assertIsNotNone(self.pending())
        with self.assertRaisesRegex(ValueError, "pending or uncertain"):
            DurableLedger(
                self.database, checkpoint_path=self.anchor,
                checkpoint_key=self.key,
            )
        with self.assertRaisesRegex(ValueError, "pending or uncertain"):
            self.trade("must-not-retry")
        self.assertEqual(self.ledger.balances()[0], Decimal("990.00"))

    def test_directory_sync_failure_blocks_even_matching_anchor(self):
        real_fsync = os.fsync

        def fail_directory(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("directory sync failed")
            return real_fsync(fd)

        with patch(
            "ariyan_trading.trust_anchor.os.fsync",
            side_effect=fail_directory,
        ):
            with self.assertRaises(PublicationUncertain):
                self.trade()

        self.assertEqual(read_anchor(self.anchor, self.key)[0], 1)
        self.assertIsNotNone(self.pending())
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            with self.assertRaisesRegex(ValueError, "pending or uncertain"):
                verify_checkpoint(
                    db, self.ledger.opening_cash, self.anchor, self.key
                )
        finally:
            db.rollback()


if __name__ == "__main__":
    unittest.main()
