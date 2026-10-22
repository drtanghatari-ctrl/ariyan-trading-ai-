"""A006: checkpoint verification requires an active SQLite snapshot."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointSnapshotA006Tests(unittest.TestCase):

    def test_verification_without_transaction_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = DurableLedger(
                root / "ledger.sqlite",
                opening_cash="1000.00",
            )
            try:
                digest = verify_protected_journal(
                    ledger.db,
                    ledger.opening_cash,
                )
                sequence = ledger.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]

                key = b"S" * 32
                anchor_path = root / "checkpoint.json"
                anchor = create_anchor(sequence, digest, key)
                write_anchor(anchor_path, anchor, key)

                self.assertFalse(ledger.db.in_transaction)

                with self.assertRaisesRegex(
                    ValueError, "active SQLite transaction"
                ):
                    verify_checkpoint(
                        ledger.db,
                        ledger.opening_cash,
                        anchor_path,
                        key,
                    )
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
