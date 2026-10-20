import unittest
from decimal import Decimal

from ariyan_trading.accounting import (
    CASH_STEP,
    QUANTITY_STEP,
    safe_purchase,
    trade_cost,
)


class AccountingInvariantTests(unittest.TestCase):

    def test_posted_cost_never_exceeds_budget(self):
        budgets = (
            "0.01", "0.10", "1.00",
            "10.00", "100.00",
        )
        prices = (
            "0.0001", "0.03", "0.333333",
            "1.99", "3", "17.777777",
        )

        for budget in budgets:
            for price in prices:
                with self.subTest(budget=budget, price=price):
                    quantity, cost = safe_purchase(
                        budget, price
                    )
                    self.assertGreaterEqual(quantity, 0)
                    self.assertGreaterEqual(cost, 0)
                    self.assertLessEqual(
                        cost, Decimal(budget)
                    )
                    self.assertEqual(
                        quantity % QUANTITY_STEP, 0
                    )
                    self.assertEqual(
                        cost % CASH_STEP, 0
                    )

    def test_posted_cost_matches_calculation(self):
        quantity, cost = safe_purchase("10.00", "3")
        self.assertEqual(cost, trade_cost(quantity, "3"))

    def test_zero_budget_produces_no_trade(self):
        quantity, cost = safe_purchase("0.00", "10")
        self.assertEqual(quantity, Decimal("0"))
        self.assertEqual(cost, Decimal("0.00"))

    def test_invalid_price_rejected(self):
        with self.assertRaises(ValueError):
            safe_purchase("10.00", "0")


if __name__ == "__main__":
    unittest.main()
