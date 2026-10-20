import unittest
from decimal import Decimal

from ariyan_trading.ledger import DecimalLedger


class LedgerTests(unittest.TestCase):

    def test_opening_balance(self):
        ledger = DecimalLedger("1000.00")
        self.assertEqual(
            ledger.balances(),
            (Decimal("1000.00"), Decimal("0")),
        )

    def test_buy_and_sell_reconcile(self):
        ledger = DecimalLedger("1000.00")
        ledger.record_buy("2", "10.25")
        ledger.record_sell("1", "12.50")

        self.assertEqual(
            ledger.balances(),
            (Decimal("992.00"), Decimal("1")),
        )
        self.assertTrue(
            ledger.reconcile("992.00", "1")
        )

    def test_insufficient_cash_rejected(self):
        ledger = DecimalLedger("10.00")
        with self.assertRaises(ValueError):
            ledger.record_buy("2", "10")
        self.assertEqual(len(ledger.entries), 0)

    def test_oversell_rejected(self):
        ledger = DecimalLedger("100.00")
        ledger.record_buy("1", "10")
        with self.assertRaises(ValueError):
            ledger.record_sell("2", "10")
        self.assertEqual(len(ledger.entries), 1)

    def test_reconciliation_detects_difference(self):
        ledger = DecimalLedger("100.00")
        ledger.record_buy("1", "10")
        self.assertFalse(
            ledger.reconcile("100.00", "1")
        )

    def test_entries_are_immutable(self):
        ledger = DecimalLedger("100.00")
        entry = ledger.record_buy("1", "10")
        with self.assertRaises(AttributeError):
            entry.action = "SELL"

    def test_sequence_numbers(self):
        ledger = DecimalLedger("100.00")
        first = ledger.record_buy("1", "10")
        second = ledger.record_sell("1", "11")
        self.assertEqual((first.sequence, second.sequence), (1, 2))


if __name__ == "__main__":
    unittest.main()
