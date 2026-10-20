"""ARIYAN Trading AI: offline paper-trading prototype."""

import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RiskLimits:
    max_trade_fraction: float = 0.10
    max_position_fraction: float = 0.25

    def __post_init__(self):
        for value in (
            self.max_trade_fraction,
            self.max_position_fraction,
        ):
            if not 0 < value <= 1:
                raise ValueError("Risk fractions must be within (0, 1]")


def validate_prices(prices):
    values = list(prices)
    if len(values) < 5:
        raise ValueError("At least five prices required")
    if not all(
        isinstance(p, (int, float))
        and not isinstance(p, bool)
        and math.isfinite(p)
        and p > 0
        for p in values
    ):
        raise ValueError("Prices must be finite positive numbers")
    return values


def signal(prices):
    values = validate_prices(prices)
    short = sum(values[-3:]) / 3
    long = sum(values[-5:]) / 5
    if short > long:
        return "BUY"
    if short < long:
        return "SELL"
    return "HOLD"


class PaperEngine:
    def __init__(self, db_path, cash=10000.0, limits=None):
        if not math.isfinite(cash) or cash <= 0:
            raise ValueError("Initial cash must be positive")
        self.cash = float(cash)
        self.units = 0.0
        self.limits = limits or RiskLimits()
        self.db_path = str(Path(db_path))
        with sqlite3.connect(self.db_path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY,
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    units REAL NOT NULL,
                    cash_after REAL NOT NULL
                )
            """)

    def execute(self, action, price):
        if action not in ("BUY", "SELL", "HOLD"):
            raise ValueError("Unknown action")
        if (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            raise ValueError("Invalid price")

        if action == "HOLD":
            return None

        equity = self.cash + self.units * price

        if action == "BUY":
            budget = min(
                self.cash,
                equity * self.limits.max_trade_fraction,
                max(
                    0.0,
                    equity * self.limits.max_position_fraction
                    - self.units * price,
                ),
            )
            if budget <= 0:
                return None
            quantity = budget / price
            self.cash -= budget
            self.units += quantity
        else:
            if self.units <= 0:
                return None
            quantity = self.units
            self.cash += quantity * price
            self.units = 0.0

        with sqlite3.connect(self.db_path) as db:
            db.execute(
                """INSERT INTO trades
                (action, price, units, cash_after)
                VALUES (?, ?, ?, ?)""",
                (action, price, quantity, self.cash),
            )

        return {
            "action": action,
            "price": price,
            "units": quantity,
            "cash": self.cash,
        }
