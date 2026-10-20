import unittest
from decimal import Decimal

from ariyan_trading.ledger_validation import bounded_decimal


class DecimalBoundsTests(unittest.TestCase):

    def test_normal_value(self):
        self.assertEqual(
            bounded_decimal("123.456"),
            Decimal("123.456"),
        )

    def test_reject_large_magnitude(self):
        with self.assertRaises(ValueError):
            bounded_decimal("1e1000000")

    def test_reject_excessive_precision(self):
        with self.assertRaises(ValueError):
            bounded_decimal("0.12345678901234567890")

    def test_reject_nonfinite(self):
        for value in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    bounded_decimal(value)

    def test_reject_float(self):
        with self.assertRaises(TypeError):
            bounded_decimal(0.1)


if __name__ == "__main__":
    unittest.main()
