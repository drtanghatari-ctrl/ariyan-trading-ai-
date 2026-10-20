import unittest
from decimal import Decimal

from ariyan_trading.accounting import (
    affordable_quantity,
    cash_amount,
    decimal_value,
    quantity_amount,
    trade_cost,
)


class AccountingTests(unittest.TestCase):

    def test_decimal_exactness(self):
        result = (
            decimal_value("0.10")
            + decimal_value("0.20")
        )
        self.assertEqual(result, Decimal("0.30"))

    def test_float_rejected(self):
        with self.assertRaises(TypeError):
            decimal_value(0.1)

    def test_cash_rounding(self):
        self.assertEqual(
            cash_amount("1.005"),
            Decimal("1.00"),
        )
        self.assertEqual(
            cash_amount("1.015"),
            Decimal("1.02"),
        )

    def test_quantity_rounds_down(self):
        self.assertEqual(
            quantity_amount("1.123456789"),
            Decimal("1.12345678"),
        )

    def test_affordable_quantity(self):
        quantity = affordable_quantity("10.00", "3")
        self.assertEqual(
            quantity,
            Decimal("3.33333333"),
        )
        self.assertLessEqual(
            quantity * Decimal("3"),
            Decimal("10.00"),
        )

    def test_trade_cost(self):
        self.assertEqual(
            trade_cost("2.5", "3.20"),
            Decimal("8.00"),
        )

    def test_invalid_values(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    decimal_value(value)


if __name__ == "__main__":
    unittest.main()
