"""Strict Decimal validation for future durable ledger entries."""

from decimal import Decimal, localcontext

from .accounting import (
    CASH_STEP,
    QUANTITY_STEP,
    decimal_value,
    trade_cost,
)


def exact_cash(value):
    amount = bounded_decimal(value)
    if amount < 0:
        raise ValueError("Negative cash amount")
    with localcontext() as ctx:
        ctx.prec = 50
        if amount != amount.quantize(CASH_STEP):
            raise ValueError("Cash precision exceeds two decimals")
        return amount.quantize(CASH_STEP)


def exact_quantity(value):
    quantity = bounded_decimal(value)
    if quantity <= 0:
        raise ValueError("Quantity must be positive")
    with localcontext() as ctx:
        ctx.prec = 50
        if quantity != quantity.quantize(QUANTITY_STEP):
            raise ValueError("Quantity precision exceeds eight decimals")
        return quantity.quantize(QUANTITY_STEP)


def validated_trade(quantity, price):
    quantity = exact_quantity(quantity)
    price = bounded_decimal(price)

    if price <= 0:
        raise ValueError("Price must be positive")

    with localcontext() as ctx:
        ctx.prec = 50
        cost = trade_cost(quantity, price)

    if cost <= 0:
        raise ValueError("Trade value rounds to zero")

    return quantity, price, cost


def bounded_decimal(value, maximum_digits=24, maximum_places=12):
    """Validate a finite Decimal within supported precision bounds."""
    amount = decimal_value(value)

    if maximum_digits <= 0 or maximum_places < 0:
        raise ValueError("Invalid precision limits")

    sign, digits, exponent = amount.as_tuple()

    if len(digits) > maximum_digits:
        raise ValueError("Too many significant digits")

    if exponent < -maximum_places:
        raise ValueError("Too many decimal places")

    if exponent > maximum_digits:
        raise ValueError("Magnitude exceeds supported range")

    if amount.adjusted() >= maximum_digits:
        raise ValueError("Magnitude exceeds supported range")

    return amount


def replay_ledger_balances(db, opening_cash):
    """Validate journal economics against opening cash in the caller's snapshot."""
    with localcontext() as ctx:
        ctx.prec = 50
        cash = opening_cash
        units = Decimal("0")

        rows = db.execute(
            "SELECT sequence,action,quantity,price,"
            "cash_delta,units_delta "
            "FROM ledger_entries ORDER BY sequence"
        )

        expected_sequence = 1

        for (
            sequence, action, quantity, price,
            cash_delta, units_delta,
        ) in rows:
            if sequence != expected_sequence:
                raise ValueError("Journal sequence gap")

            if action not in ("BUY", "SELL"):
                raise ValueError("Unsupported journal action")

            qty, _, cost = validated_trade(
                quantity, price
            )

            if action == "BUY":
                if Decimal(units_delta) != qty:
                    raise ValueError("Invalid BUY units delta")
                if Decimal(cash_delta) != -cost:
                    raise ValueError("Invalid BUY cash delta")
                if cost > cash:
                    raise ValueError("Journal overspent cash")
                cash -= cost
                units += qty
            else:
                if Decimal(units_delta) != -qty:
                    raise ValueError("Invalid SELL units delta")
                if Decimal(cash_delta) != cost:
                    raise ValueError("Invalid SELL cash delta")
                if qty > units:
                    raise ValueError("Journal oversold units")
                cash += cost
                units -= qty
            expected_sequence += 1

    return cash, units
