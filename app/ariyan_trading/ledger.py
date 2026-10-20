"""Independent Decimal accounting ledger.

Experimental A004 module. No integration with legacy portfolio.
"""

from dataclasses import dataclass
from decimal import Decimal

from .accounting import (
    cash_amount,
    available_cash,
    decimal_value,
    quantity_amount,
    trade_cost,
)


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    action: str
    cash_delta: Decimal
    units_delta: Decimal


class DecimalLedger:
    def __init__(self, opening_cash):
        self.opening_cash = available_cash(opening_cash)
        self._entries = []

    @property
    def entries(self):
        return tuple(self._entries)

    def balances(self):
        cash = self.opening_cash
        units = Decimal("0")

        for entry in self._entries:
            cash += entry.cash_delta
            units += entry.units_delta

        return cash, units

    def record_buy(self, quantity, price):
        quantity = quantity_amount(quantity)
        price = decimal_value(price)

        if quantity <= 0 or price <= 0:
            raise ValueError("Invalid purchase")

        cost = trade_cost(quantity, price)
        if cost <= 0:
            raise ValueError("Zero-cost purchases are prohibited")
        cash, _ = self.balances()

        if cost > cash:
            raise ValueError("Insufficient cash")

        entry = LedgerEntry(
            sequence=len(self._entries) + 1,
            action="BUY",
            cash_delta=-cost,
            units_delta=quantity,
        )
        self._entries.append(entry)
        return entry

    def record_sell(self, quantity, price):
        quantity = quantity_amount(quantity)
        price = decimal_value(price)

        if quantity <= 0 or price <= 0:
            raise ValueError("Invalid sale")

        proceeds = trade_cost(quantity, price)
        if proceeds <= 0:
            raise ValueError("Zero-proceeds sales are prohibited")
        _, units = self.balances()

        if quantity > units:
            raise ValueError("Insufficient units")

        entry = LedgerEntry(
            sequence=len(self._entries) + 1,
            action="SELL",
            cash_delta=proceeds,
            units_delta=-quantity,
        )
        self._entries.append(entry)
        return entry

    def reconcile(self, expected_cash, expected_units):
        actual_cash, actual_units = self.balances()
        return (
            actual_cash == cash_amount(expected_cash)
            and actual_units == quantity_amount(expected_units)
        )
