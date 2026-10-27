"""A006 coordinator recovery boundaries under actual SIGKILL."""

import os
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.checkpoint_coordinator import (
    PENDING, execute_checkpointed_trade,
)
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, read_anchor, write_anchor

KEY = b"A006-process-kill-test-key-only!!"

CHILD = r"""
import os
import signal
import stat
import sys
from unittest.mock import patch

from ariyan_trading import checkpoint_coordinator as coordinator
from ariyan_trading.durable_ledger import DurableLedger

database, anchor, phase = sys.argv[1:]
key = b"A006-process-kill-test-key-only!!"
ledger = DurableLedger(database)

def die():
    os.kill(os.getpid(), signal.SIGKILL)

real_append = coordinator.append_journal_commitment
real_write = coordinator.write_anchor
real_fsync = os.fsync

def interrupted_append(*args, **kwargs):
    result = real_append(*args, **kwargs)
    if phase == "before_commit":
        die()
    return result

def interrupted_write(*args, **kwargs):
    if phase == "after_commit":
        die()
    result = real_write(*args, **kwargs)
    if phase == "after_publication":
        die()
    return result

def interrupted_fsync(fd):
    if phase == "after_replace" and stat.S_ISDIR(os.fstat(fd).st_mode):
        die()
    return real_fsync(fd)

with patch.object(
    coordinator, "append_journal_commitment", interrupted_append
), patch.object(
    coordinator, "write_anchor", interrupted_write
), patch(
    "ariyan_trading.trust_anchor.os.fsync",
    side_effect=interrupted_fsync,
):
    coordinator.execute_checkpointed_trade(
        ledger, "BUY", "killed-at-boundary", "1", "10.00",
        anchor_path=anchor, key=key,
    )

raise RuntimeError("Termination boundary was not reached")
"""


class CoordinatorProcessKillA006Tests(unittest.TestCase):
    def check_boundary(self, phase):
        for mode in ("DELETE", "WAL"):
            with self.subTest(phase=phase, journal_mode=mode):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    database = root / "ledger.sqlite"
                    anchor = root / "anchor.json"
                    ledger = DurableLedger(
                        database, opening_cash="1000.00"
                    )
                    try:
                        actual = ledger.db.execute(
                            "PRAGMA journal_mode=" + mode
                        ).fetchone()[0]
                        self.assertEqual(actual.upper(), mode)
                        ledger.db.execute("BEGIN")
                        digest = verify_protected_journal(
                            ledger.db, ledger.opening_cash
                        )
                        ledger.db.commit()
                        write_anchor(
                            anchor, create_anchor(0, digest, KEY), KEY
                        )
                    finally:
                        ledger.close()

                    before = anchor.read_bytes()
                    project = Path(__file__).resolve().parents[1]
                    env = os.environ.copy()
                    env["PYTHONPATH"] = str(project / "app")
                    child = subprocess.run(
                        [
                            sys.executable, "-c", CHILD,
                            str(database), str(anchor), phase,
                        ],
                        cwd=project, env=env,
                        capture_output=True, text=True, timeout=15,
                    )
                    self.assertEqual(
                        child.returncode, -signal.SIGKILL,
                        msg=child.stdout + child.stderr,
                    )

                    db = sqlite3.connect(database)
                    try:
                        self.assertEqual(
                            db.execute("PRAGMA integrity_check").fetchall(),
                            [("ok",)],
                        )
                        count = db.execute(
                            "SELECT COUNT(*) FROM ledger_entries"
                        ).fetchone()[0]
                        pending = db.execute(
                            "SELECT value FROM ledger_meta WHERE key=?",
                            (PENDING,),
                        ).fetchone()
                    finally:
                        db.close()

                    if phase == "before_commit":
                        self.assertEqual(count, 0)
                        self.assertIsNone(pending)
                        self.assertEqual(anchor.read_bytes(), before)
                        reader = DurableLedger(
                            database, checkpoint_path=anchor,
                            checkpoint_key=KEY,
                        )
                        try:
                            self.assertEqual(
                                reader.balances()[0], Decimal("1000.00")
                            )
                        finally:
                            reader.close()
                    else:
                        self.assertEqual(count, 1)
                        self.assertIsNotNone(pending)
                        expected_sequence = (
                            0 if phase == "after_commit" else 1
                        )
                        self.assertEqual(
                            read_anchor(anchor, KEY)[0],
                            expected_sequence,
                        )
                        with self.assertRaisesRegex(
                            ValueError, "pending or uncertain"
                        ):
                            DurableLedger(
                                database, checkpoint_path=anchor,
                                checkpoint_key=KEY,
                            )

                        writer = DurableLedger(database)
                        try:
                            self.assertEqual(
                                writer.balances()[0], Decimal("990.00")
                            )
                            with self.assertRaisesRegex(
                                ValueError, "pending or uncertain"
                            ):
                                execute_checkpointed_trade(
                                    writer, "BUY", "blocked-retry",
                                    "1", "10.00",
                                    anchor_path=anchor, key=KEY,
                                )
                            self.assertEqual(
                                writer.balances()[0], Decimal("990.00")
                            )
                        finally:
                            writer.close()

    def test_killed_before_commit_rolls_back(self):
        self.check_boundary("before_commit")

    def test_killed_after_commit_preserves_pending_trade(self):
        self.check_boundary("after_commit")

    def test_killed_after_replace_blocks_matching_anchor(self):
        self.check_boundary("after_replace")

    def test_killed_after_publication_before_clearance_blocks_restart(self):
        self.check_boundary("after_publication")


if __name__ == "__main__":
    unittest.main()
