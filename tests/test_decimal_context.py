import unittest
from decimal import Decimal, localcontext

from ariyan_trading.ledger_validation import (
    exact_cash,
    exact_quantity,
    validated_trade,
)


class DecimalContextTests(unittest.TestCase):

    def test_cash_independent_of_context(self):
        for precision in (6, 12, 28, 50):
            with self.subTest(precision=precision):
                with localcontext() as ctx:
                    ctx.prec = precision
                    result = exact_cash("123456789.12")
                self.assertEqual(
                    result, Decimal("123456789.12")
                )

    def test_quantity_independent_of_context(self):
        for precision in (6, 12, 28, 50):
            with self.subTest(precision=precision):
                with localcontext() as ctx:
                    ctx.prec = precision
                    result = exact_quantity("1.12345678")
                self.assertEqual(
                    result, Decimal("1.12345678")
                )

    def test_trade_independent_of_context(self):
        for precision in (6, 12, 28, 50):
            with self.subTest(precision=precision):
                with localcontext() as ctx:
                    ctx.prec = precision
                    _, _, cost = validated_trade(
                        "1.12345678", "123.45"
                    )
                self.assertEqual(
                    cost, Decimal("138.69")
                )

    def test_reject_excess_precision(self):
        with localcontext() as ctx:
            ctx.prec = 6
            with self.assertRaises(ValueError):
                exact_quantity("1.123456789")


if __name__ == "__main__":
    unittest.main()
