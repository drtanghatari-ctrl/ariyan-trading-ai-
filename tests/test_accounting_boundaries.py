"""Financial precision and zero-cost transaction safety."""

import unittest
from decimal import Decimal

from ariyan_trading.accounting import safe_purchase
from ariyan_trading.ledger import DecimalLedger


class AccountingBoundaryTests(unittest.TestCase):

    def test_no_free_units_from_tiny_price(self):
        quantity, cost = safe_purchase(
            "1.00", "0.0000000001"
        )
        self.assertTrue(
            quantity == 0 or cost > 0,
            "Positive units must not have zero posted cost",
        )

    def test_ledger_rejects_zero_cost_buy(self):
        ledger = DecimalLedger("100.00")
        with self.assertRaises(ValueError):
            ledger.record_buy("0.00000001", "0.01")
        self.assertEqual(len(ledger.entries), 0)

    def test_ledger_rejects_zero_proceeds_sell(self):
        ledger = DecimalLedger("100.00")
        ledger.record_buy("1", "1.00")
        with self.assertRaises(ValueError):
            ledger.record_sell("0.00000001", "0.01")
        self.assertEqual(len(ledger.entries), 1)

    def test_cash_input_cannot_round_up(self):
        ledger = DecimalLedger("0.006")
        self.assertLessEqual(
            ledger.opening_cash,
            Decimal("0.006"),
            "Opening cash must not exceed supplied funds",
        )


if __name__ == "__main__":
    unittest.main()


class TinyPurchaseTests(unittest.TestCase):

    def test_no_free_units_with_one_cent_budget(self):
        quantity, cost = safe_purchase(
            "0.01", "0.00000001"
        )
        self.assertTrue(
            quantity == 0 or cost > 0,
            "Positive quantity cannot have zero posted cost",
        )

    def test_budget_below_one_cent(self):
        quantity, cost = safe_purchase(
            "0.006", "1.00"
        )
        self.assertEqual(quantity, Decimal("0"))
        self.assertEqual(cost, Decimal("0.00"))
