"""A006: authenticated checkpoint verification under WAL concurrency."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointConcurrencyA006Tests(unittest.TestCase):
    def test_historical_snapshot_and_fresh_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ledger.sqlite"
            anchor_path = root / "checkpoint.json"
            key = b"T" * 32

            ledger = DurableLedger(database, opening_cash="1000.00")
            reader = None

            try:
                mode = ledger.db.execute(
                    "PRAGMA journal_mode=WAL"
                ).fetchone()[0]
                self.assertEqual(mode.lower(), "wal")

                digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                write_anchor(
                    anchor_path, create_anchor(0, digest, key), key
                )

                reader = sqlite3.connect(
                    database, isolation_level=None, timeout=5
                )

                reader.execute("BEGIN")
                initial = reader.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
                self.assertEqual(initial, 0)

                ledger.record_buy("a006-concurrency", "1", "10.00")

                self.assertEqual(
                    verify_checkpoint(
                        reader, ledger.opening_cash,
                        anchor_path, key
                    ),
                    (0, digest),
                )

                reader.execute("ROLLBACK")
                reader.execute("BEGIN")

                with self.assertRaisesRegex(
                    ValueError, "Checkpoint sequence mismatch"
                ):
                    verify_checkpoint(
                        reader, ledger.opening_cash,
                        anchor_path, key
                    )

            finally:
                if reader is not None:
                    if reader.in_transaction:
                        reader.rollback()
                    reader.close()
                ledger.close()


if __name__ == "__main__":
    unittest.main()
