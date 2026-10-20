import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableSellTests(unittest.TestCase):

    def test_buy_sell_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "5", "10")
            cash, units = ledger.record_sell(
                "sell-1", "2", "12"
            )

            self.assertEqual(cash, Decimal("74.00"))
            self.assertEqual(units, Decimal("3"))
            ledger.close()

            reopened = DurableLedger(path)
            self.assertEqual(
                reopened.balances(),
                (Decimal("74.00"), Decimal("3")),
            )
            reopened.close()

    def test_overselling_rolls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")

            with self.assertRaises(ValueError):
                ledger.record_sell("sell-1", "2", "10")

            self.assertEqual(
                ledger.balances(),
                (Decimal("90.00"), Decimal("1")),
            )
            ledger.close()

    def test_duplicate_sell_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "3", "10")
            ledger.record_sell("sell-1", "1", "10")

            with self.assertRaises(ValueError):
                ledger.record_sell("sell-1", "1", "10")

            self.assertEqual(
                ledger.balances(),
                (Decimal("80.00"), Decimal("2")),
            )
            ledger.close()


if __name__ == "__main__":
    unittest.main()
