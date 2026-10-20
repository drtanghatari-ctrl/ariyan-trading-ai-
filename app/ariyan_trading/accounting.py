"""Deterministic decimal accounting primitives.

These primitives do not modify legacy SQLite balances.
They are not yet integrated into PaperEngine execution.
"""

from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_DOWN,
    ROUND_HALF_EVEN,
)

CASH_STEP = Decimal("0.01")
QUANTITY_STEP = Decimal("0.00000001")


def decimal_value(value):
    """Convert supported numeric input without binary float arithmetic."""
    if isinstance(value, bool):
        raise ValueError("Boolean is not a monetary value")

    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, str)):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("Invalid decimal value") from exc
    else:
        raise TypeError(
            "Use Decimal, integer, or decimal string; "
            "binary floats are not accepted"
        )

    if not result.is_finite():
        raise ValueError("Non-finite decimal value")

    return result


def cash_amount(value):
    amount = decimal_value(value)
    if amount < 0:
        raise ValueError("Negative cash amount")
    return amount.quantize(CASH_STEP, rounding=ROUND_HALF_EVEN)


def quantity_amount(value):
    amount = decimal_value(value)
    if amount < 0:
        raise ValueError("Negative quantity")
    return amount.quantize(QUANTITY_STEP, rounding=ROUND_DOWN)


def affordable_quantity(budget, price):
    budget = available_cash(budget)
    price = decimal_value(price)

    if price <= 0:
        raise ValueError("Price must be positive")

    quantity = quantity_amount(budget / price)

    if quantity * price > budget:
        raise ArithmeticError("Quantity exceeds available budget")

    return quantity


def trade_cost(quantity, price):
    quantity = quantity_amount(quantity)
    price = decimal_value(price)

    if price <= 0:
        raise ValueError("Price must be positive")

    return (quantity * price).quantize(
        CASH_STEP,
        rounding=ROUND_HALF_EVEN,
    )


def safe_purchase(budget, price):
    """Return quantity and posted cost without exceeding cash budget.

    This is a conservative paper-accounting primitive.
    Fees, slippage, and instrument-specific rules are not included.
    """
    budget = available_cash(budget)
    price = decimal_value(price)

    if price <= 0:
        raise ValueError("Price must be positive")

    quantity = affordable_quantity(budget, price)
    cost = trade_cost(quantity, price)

    if cost > budget:
        quantity = max(
            Decimal("0"),
            quantity - QUANTITY_STEP,
        )
        cost = trade_cost(quantity, price)

    if cost > budget:
        raise ArithmeticError(
            "Unable to calculate affordable posted cost"
        )

    if quantity > 0 and cost <= 0:
        return Decimal("0"), Decimal("0.00")

    return quantity, cost


def available_cash(value):
    """Floor nonnegative available funds to the cash step."""
    amount = decimal_value(value)
    if amount < 0:
        raise ValueError("Negative available cash")
    return amount.quantize(CASH_STEP, rounding=ROUND_DOWN)
