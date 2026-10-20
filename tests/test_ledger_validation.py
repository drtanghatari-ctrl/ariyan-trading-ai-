import unittest
from decimal import Decimal

from ariyan_trading.ledger_validation import (
    exact_cash,
    exact_quantity,
    validated_trade,
)


class LedgerValidationTests(unittest.TestCase):

    def test_exact_cash(self):
        self.assertEqual(exact_cash("10.25"), Decimal("10.25"))

    def test_reject_fractional_cent(self):
        with self.assertRaises(ValueError):
            exact_cash("0.006")

    def test_exact_quantity(self):
        self.assertEqual(
            exact_quantity("1.12345678"),
            Decimal("1.12345678"),
        )

    def test_reject_excess_quantity_precision(self):
        with self.assertRaises(ValueError):
            exact_quantity("1.123456789")

    def test_reject_zero_value_trade(self):
        with self.assertRaises(ValueError):
            validated_trade("0.00000001", "0.01")

    def test_valid_trade(self):
        quantity, price, cost = validated_trade("2", "3.25")
        self.assertEqual(cost, Decimal("6.50"))

    def test_reject_binary_float(self):
        with self.assertRaises(TypeError):
            exact_cash(0.1)


if __name__ == "__main__":
    unittest.main()
