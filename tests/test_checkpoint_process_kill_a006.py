"""A006 isolated SQLite child-process termination test."""

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
import sqlite3
import sys
import time
from pathlib import Path

db = sqlite3.connect(sys.argv[1], timeout=3)
db.execute("BEGIN IMMEDIATE")
db.execute(
    "INSERT INTO ledger_entries "
    "(request_id,action,quantity,price,cash_delta,units_delta) "
    "VALUES (?,?,?,?,?,?)",
    ("killed-child", "BUY", "1", "10", "-10", "1"),
)
Path(sys.argv[2]).write_text("INSERTED")
time.sleep(30)
"""


class CheckpointProcessKillA006Tests(unittest.TestCase):

    def test_killed_uncommitted_child_preserves_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "ledger.sqlite"
            anchor = root / "anchor.json"
            marker = root / "child-ready"
            key = b"A" * 32

            ledger = DurableLedger(
                database, opening_cash="1000.00"
            )
            try:
                digest = verify_protected_journal(
                    ledger.db, ledger.opening_cash
                )
                sequence = ledger.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
            finally:
                ledger.close()

            write_anchor(
                anchor,
                create_anchor(sequence, digest, key),
                key,
            )
            original_anchor = anchor.read_bytes()

            child = subprocess.Popen(
                [
                    sys.executable, "-c", CHILD,
                    str(database), str(marker),
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
                            "Child exited before insertion: " + error
                        )
                    if time.monotonic() >= deadline:
                        self.fail("Child insertion timed out")
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
                count = db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
                self.assertEqual(count, sequence)

                result = verify_checkpoint(
                    db, "1000.00", anchor, key
                )
                self.assertEqual(
                    result, (sequence, digest)
                )
                self.assertEqual(
                    anchor.read_bytes(), original_anchor
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
