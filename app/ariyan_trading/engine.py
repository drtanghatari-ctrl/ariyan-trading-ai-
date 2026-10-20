"""ARIYAN Trading AI: offline, persistent paper engine.

No broker connectivity or real financial operations.
"""
import math
import sqlite3
import uuid
from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path


def positive_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


@dataclass(frozen=True)
class RiskLimits:
    max_trade_fraction: float = 0.10
    max_position_fraction: float = 0.25

    def __post_init__(self):
        for value in (
            self.max_trade_fraction,
            self.max_position_fraction,
        ):
            if not positive_number(value) or value > 1:
                raise ValueError("Invalid risk fraction")


def validate_prices(prices):
    values = list(prices)
    if len(values) < 5:
        raise ValueError("At least five prices required")
    if not all(positive_number(p) for p in values):
        raise ValueError("Invalid price series")
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
        if not positive_number(cash):
            raise ValueError("Invalid initial cash")

        self.db_path = str(Path(db_path))
        self.limits = limits or RiskLimits()

        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""
                    CREATE TABLE IF NOT EXISTS portfolio (
                        id INTEGER PRIMARY KEY CHECK(id = 1),
                        cash REAL NOT NULL CHECK(cash >= 0),
                        units REAL NOT NULL CHECK(units >= 0)
                    )
                """)
                db.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY,
                        action TEXT NOT NULL,
                        price REAL NOT NULL,
                        units REAL NOT NULL,
                        cash_after REAL NOT NULL
                    )
                """)

                existing = db.execute(
                    "SELECT cash, units FROM portfolio WHERE id=1"
                ).fetchone()

                if existing is None:
                    historical = db.execute(
                        "SELECT COUNT(*) FROM trades"
                    ).fetchone()[0]
                    if historical:
                        raise RuntimeError(
                            "Historical trades exist without portfolio; "
                            "manual recovery required"
                        )
                    db.execute(
                        "INSERT INTO portfolio (id, cash, units) "
                        "VALUES (1, ?, 0)",
                        (float(cash),),
                    )

                columns = {
                    row[1] for row in db.execute(
                        "PRAGMA table_info(trades)"
                    )
                }
                if "request_id" not in columns:
                    db.execute(
                        "ALTER TABLE trades ADD COLUMN request_id TEXT"
                    )

                db.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "idx_trades_request_id ON trades(request_id)"
                )

                db.commit()
            except BaseException:
                db.rollback()
                raise

        self.refresh()

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(
            self.db_path,
            timeout=10,
            isolation_level=None,
        )
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def refresh(self):
        with self._connection() as db:
            row = db.execute(
                "SELECT cash, units FROM portfolio WHERE id=1"
            ).fetchone()
        if row is None:
            raise RuntimeError("Portfolio state missing")
        self.cash, self.units = row
        return self.cash, self.units

    def execute(self, action, price, request_id=None):
        if action not in ("BUY", "SELL", "HOLD"):
            raise ValueError("Unknown action")
        if not positive_number(price):
            raise ValueError("Invalid price")

        if action == "HOLD":
            self.refresh()
            return None

        if request_id is None:
            request_id = str(uuid.uuid4())
        if (
            not isinstance(request_id, str)
            or not request_id.strip()
            or len(request_id) > 128
        ):
            raise ValueError("Invalid request ID")

        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute(
                "SELECT id FROM trades WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if duplicate is not None:
                raise ValueError("Duplicate trade request")

            row = db.execute(
                "SELECT cash, units FROM portfolio WHERE id=1"
            ).fetchone()
            if row is None:
                raise RuntimeError("Portfolio state missing")

            cash, units = row
            equity = cash + units * price
            if not math.isfinite(equity):
                raise ValueError("Invalid portfolio valuation")

            if action == "BUY":
                budget = min(
                    cash,
                    equity * self.limits.max_trade_fraction,
                    max(
                        0.0,
                        equity * self.limits.max_position_fraction
                        - units * price,
                    ),
                )
                if budget <= 0:
                    db.rollback()
                    self.refresh()
                    return None
                quantity = budget / price
                new_cash = cash - budget
                new_units = units + quantity
            else:
                if units <= 0:
                    db.rollback()
                    self.refresh()
                    return None
                quantity = units
                new_cash = cash + units * price
                new_units = 0.0

            if not all(
                math.isfinite(v) and v >= 0
                for v in (quantity, new_cash, new_units)
            ) or quantity <= 0:
                raise ValueError("Invalid transaction result")

            db.execute(
                """UPDATE portfolio
                SET cash=?, units=? WHERE id=1""",
                (new_cash, new_units),
            )
            db.execute(
                """INSERT INTO trades
                (action, price, units, cash_after, request_id)
                VALUES (?, ?, ?, ?, ?)""",
                (action, price, quantity, new_cash, request_id),
            )
            db.commit()

            self.cash = new_cash
            self.units = new_units

            return {
                "action": action,
                "price": price,
                "units": quantity,
                "cash": new_cash,
            }
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
