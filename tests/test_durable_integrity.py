import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableIntegrityTests(unittest.TestCase):

    def test_existing_empty_database_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            sqlite3.connect(path).close()

            with self.assertRaises(ValueError):
                DurableLedger(path, "100.00")

    def test_missing_opening_balance_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.close()

            with sqlite3.connect(path) as db:
                db.execute(
                    "DELETE FROM ledger_meta "
                    "WHERE key='opening_cash'"
                )

            with self.assertRaises(ValueError):
                DurableLedger(path, "100.00")


if __name__ == "__main__":
    unittest.main()
