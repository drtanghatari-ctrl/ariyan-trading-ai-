"""A006 process termination after journal commit, before anchor publication."""

import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.checkpoint_verifier import verify_checkpoint
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


CHILD = """
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[3])
from ariyan_trading.durable_ledger import DurableLedger

ledger = DurableLedger(
    Path(sys.argv[1]), opening_cash="1000.00"
)
ledger.record_buy("postcommit-child", "1", "10")

# This marker is written only after record_buy returns
# following its SQLite COMMIT.
Path(sys.argv[2]).write_text("COMMITTED")
time.sleep(30)
"""


class PostcommitKillA006Tests(unittest.TestCase):

    def test_committed_journal_survives_with_stale_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ledger.sqlite"
            anchor = root / "anchor.json"
            marker = root / "committed"
            key = b"A" * 32

            ledger = DurableLedger(
                database, opening_cash="1000.00"
            )
            try:
                original_digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                original_sequence = ledger.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
            finally:
                ledger.close()

            write_anchor(
                anchor,
                create_anchor(
                    original_sequence, original_digest, key
                ),
                key,
            )
            original_anchor = anchor.read_bytes()

            app_path = str(
                Path(__file__).resolve().parents[1] / "app"
            )
            child = subprocess.Popen(
                [
                    sys.executable, "-c", CHILD,
                    str(database), str(marker), app_path,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not marker.exists():
                    if child.poll() is not None:
                        error = child.stderr.read().decode(
                            errors="replace"
                        )
                        self.fail(
                            "Child exited before commit: " + error
                        )
                    if time.monotonic() >= deadline:
                        self.fail("Commit marker timed out")
                    time.sleep(0.05)

                self.assertIsNone(child.poll())
                child.kill()
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=5)
                child.stderr.close()

            db = sqlite3.connect(database)
            try:
                db.execute("BEGIN")
                sequence = db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
                digest = verify_protected_journal(
                    db, "1000.00"
                )
                self.assertEqual(
                    sequence, original_sequence + 1
                )
                self.assertNotEqual(
                    digest, original_digest
                )
                self.assertEqual(
                    anchor.read_bytes(), original_anchor
                )

                with self.assertRaisesRegex(
                    ValueError, "Checkpoint sequence mismatch"
                ):
                    verify_checkpoint(
                        db, "1000.00", anchor, key
                    )

                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM ledger_entries"
                    ).fetchone()[0],
                    sequence,
                )
                self.assertEqual(
                    anchor.read_bytes(), original_anchor
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
