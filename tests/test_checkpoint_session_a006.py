"""A006: repeated reads remain bound to the opening checkpoint."""

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointSessionA006Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        database = root / "ledger.sqlite"
        anchor = root / "anchor.json"
        key = b"A006-session-regression-key-only!!"

        self.writer = DurableLedger(database, opening_cash="1000.00")
        self.addCleanup(self.writer.close)
        mode = self.writer.db.execute(
            "PRAGMA journal_mode=WAL"
        ).fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

        self.writer.db.execute("BEGIN")
        try:
            digest = verify_protected_journal(
                self.writer.db, self.writer.opening_cash
            )
            self.writer.db.execute("COMMIT")
        except BaseException:
            self.writer.db.rollback()
            raise
        write_anchor(anchor, create_anchor(0, digest, key), key)

        self.reader = DurableLedger(
            database, checkpoint_path=anchor, checkpoint_key=key
        )
        self.addCleanup(self.reader.close)

    def test_unchanged_checkpoint_allows_repeated_reads(self):
        expected = (Decimal("1000.00"), Decimal("0"))
        self.assertEqual(self.reader.balances(), expected)
        self.assertEqual(self.reader.balances(), expected)
        self.assertFalse(self.reader.db.in_transaction)

    def test_existing_session_rejects_later_committed_trade(self):
        self.assertEqual(
            self.reader.balances()[0], Decimal("1000.00")
        )
        self.writer.record_buy("later-trade", "1", "10.00")

        for _ in range(2):
            with self.assertRaisesRegex(
                ValueError, "Checkpoint sequence mismatch"
            ):
                self.reader.balances()
            self.assertFalse(self.reader.db.in_transaction)

        self.assertEqual(
            self.writer.balances(),
            (Decimal("990.00"), Decimal("1.00000000")),
        )


if __name__ == "__main__":
    unittest.main()
