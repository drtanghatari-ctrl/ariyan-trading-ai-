import sqlite3
from contextlib import closing
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class ProcessCrashRecoveryTests(unittest.TestCase):

    def test_uncommitted_transaction_is_rolled_back(self):
        worker = """
import os
import sqlite3
import sys

db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute("BEGIN IMMEDIATE")
db.execute(
    "INSERT INTO ledger_entries "
    "(request_id, action, quantity, price, "
    "cash_delta, units_delta) "
    "VALUES (?, ?, ?, ?, ?, ?)",
    ("crashed-buy", "BUY", "1", "10", "-10", "1"),
)
os._exit(7)
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.close()

            result = subprocess.run(
                [sys.executable, "-c", worker, str(path)],
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(
                result.returncode,
                7,
                msg=result.stderr,
            )

            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(
                    db.execute(
                        "PRAGMA integrity_check"
                    ).fetchall(),
                    [("ok",)],
                )

                count = db.execute(
                    "SELECT COUNT(*) FROM ledger_entries "
                    "WHERE request_id='crashed-buy'"
                ).fetchone()[0]

                self.assertEqual(count, 0)

            recovered = DurableLedger(path)
            try:
                cash, units = recovered.balances()
                self.assertEqual(cash, 100)
                self.assertEqual(units, 0)
            finally:
                recovered.close()


    def test_committed_transaction_survives_crash(self):
        worker = """
import os
import sys
from ariyan_trading.durable_ledger import DurableLedger

ledger = DurableLedger(sys.argv[1])
ledger.record_buy("committed-buy", "1", "10")

# Terminate without calling close().
os._exit(7)
"""

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "committed.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.close()

            result = subprocess.run(
                [sys.executable, "-c", worker, str(path)],
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(
                result.returncode,
                7,
                msg=result.stderr,
            )

            with closing(sqlite3.connect(path)) as db, db:
                self.assertEqual(
                    db.execute(
                        "PRAGMA integrity_check"
                    ).fetchall(),
                    [("ok",)],
                )

                count = db.execute(
                    "SELECT COUNT(*) FROM ledger_entries "
                    "WHERE request_id='committed-buy'"
                ).fetchone()[0]

                self.assertEqual(count, 1)

            recovered = DurableLedger(path)
            try:
                cash, units = recovered.balances()
                self.assertEqual(cash, 90)
                self.assertEqual(units, 1)
            finally:
                recovered.close()


if __name__ == "__main__":
    unittest.main()
