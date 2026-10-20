import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableRecoveryTests(unittest.TestCase):

    def test_reject_modified_cash_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")
            ledger.close()

            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE ledger_entries "
                    "SET cash_delta='-1.00'"
                )

            with self.assertRaises(ValueError):
                DurableLedger(path)

    def test_reject_modified_units_delta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")
            ledger.close()

            with sqlite3.connect(path) as db:
                db.execute(
                    "UPDATE ledger_entries "
                    "SET units_delta='100'"
                )

            with self.assertRaises(ValueError):
                DurableLedger(path)

    def test_reject_sequence_gap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")
            ledger.record_buy("buy-2", "1", "10")
            ledger.close()

            with sqlite3.connect(path) as db:
                db.execute(
                    "DELETE FROM ledger_entries "
                    "WHERE sequence=1"
                )

            with self.assertRaises(ValueError):
                DurableLedger(path)


if __name__ == "__main__":
    unittest.main()
