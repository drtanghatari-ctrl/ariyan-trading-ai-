import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableBuyTests(unittest.TestCase):

    def test_buy_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            cash, units = ledger.record_buy("buy-1", "2", "10.25")

            self.assertEqual(cash, Decimal("79.50"))
            self.assertEqual(units, Decimal("2"))
            ledger.close()

            reopened = DurableLedger(path)
            self.assertEqual(
                reopened.balances(),
                (Decimal("79.50"), Decimal("2")),
            )
            reopened.close()

    def test_insufficient_cash_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "10.00")

            with self.assertRaises(ValueError):
                ledger.record_buy("buy-1", "2", "10")

            self.assertEqual(
                ledger.balances(),
                (Decimal("10.00"), Decimal("0")),
            )
            ledger.close()

    def test_duplicate_request_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")

            with self.assertRaises(ValueError):
                ledger.record_buy("buy-1", "1", "10")

            self.assertEqual(
                ledger.balances(),
                (Decimal("90.00"), Decimal("1")),
            )
            ledger.close()


if __name__ == "__main__":
    unittest.main()
