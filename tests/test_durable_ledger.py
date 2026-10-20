import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableLedgerTests(unittest.TestCase):

    def test_create_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "1000.25")
            self.assertEqual(
                ledger.opening_cash, Decimal("1000.25")
            )
            ledger.close()

            reopened = DurableLedger(path)
            self.assertEqual(
                reopened.opening_cash, Decimal("1000.25")
            )
            reopened.close()

    def test_reject_opening_cash_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.close()

            with self.assertRaises(ValueError):
                DurableLedger(path, "200.00")

    def test_reject_fractional_cent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            with self.assertRaises(ValueError):
                DurableLedger(path, "0.006")

    def test_reject_corrupted_opening_balance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.close()

            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE ledger_meta SET value='NaN' "
                    "WHERE key='opening_cash'"
                )

            with self.assertRaises(ValueError):
                DurableLedger(path)


if __name__ == "__main__":
    unittest.main()
