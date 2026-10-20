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
