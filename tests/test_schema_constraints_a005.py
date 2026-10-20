import sqlite3
import unittest

from ariyan_trading.schema_validation import validate_ledger_schema


class SchemaConstraintsA005Tests(unittest.TestCase):

    def make_database(self, *, autoincrement, action_check):
        db = sqlite3.connect(":memory:")

        sequence = (
            "INTEGER PRIMARY KEY AUTOINCREMENT"
            if autoincrement
            else "INTEGER PRIMARY KEY"
        )

        action = (
            "TEXT NOT NULL CHECK(action IN ('BUY','SELL'))"
            if action_check
            else "TEXT NOT NULL"
        )

        db.execute(
            "CREATE TABLE ledger_meta ("
            "key TEXT PRIMARY KEY, "
            "value TEXT NOT NULL)"
        )

        db.execute(
            "CREATE TABLE ledger_entries ("
            f"sequence {sequence}, "
            "request_id TEXT NOT NULL UNIQUE, "
            f"action {action}, "
            "quantity TEXT NOT NULL, "
            "price TEXT NOT NULL, "
            "cash_delta TEXT NOT NULL, "
            "units_delta TEXT NOT NULL)"
        )

        return db

    def test_valid_schema_is_accepted(self):
        db = self.make_database(
            autoincrement=True,
            action_check=True,
        )
        try:
            validate_ledger_schema(db)
        finally:
            db.close()

    def test_missing_autoincrement_is_rejected(self):
        db = self.make_database(
            autoincrement=False,
            action_check=True,
        )
        try:
            with self.assertRaises(ValueError):
                validate_ledger_schema(db)
        finally:
            db.close()

    def test_missing_action_check_is_rejected(self):
        db = self.make_database(
            autoincrement=True,
            action_check=False,
        )
        try:
            with self.assertRaises(ValueError):
                validate_ledger_schema(db)
        finally:
            db.close()


    def test_existing_a004_database_reopens(self):
        import tempfile
        from pathlib import Path

        from ariyan_trading.durable_ledger import DurableLedger

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy_a004.sqlite"

            with sqlite3.connect(path) as db:
                db.execute(
                    "CREATE TABLE ledger_meta ("
                    "key TEXT PRIMARY KEY, "
                    "value TEXT NOT NULL)"
                )

                db.execute(
                    "CREATE TABLE ledger_entries ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "request_id TEXT NOT NULL UNIQUE, "
                    "action TEXT NOT NULL "
                    "CHECK(action IN ('BUY','SELL')), "
                    "quantity TEXT NOT NULL, "
                    "price TEXT NOT NULL, "
                    "cash_delta TEXT NOT NULL, "
                    "units_delta TEXT NOT NULL)"
                )

                db.execute(
                    "INSERT INTO ledger_meta(key,value) "
                    "VALUES ('opening_cash','100.00')"
                )

                db.execute(
                    "INSERT INTO ledger_entries "
                    "(request_id,action,quantity,price,"
                    "cash_delta,units_delta) "
                    "VALUES (?,?,?,?,?,?)",
                    (
                        "legacy-buy",
                        "BUY",
                        "2",
                        "10",
                        "-20",
                        "2",
                    ),
                )

                db.commit()

            ledger = DurableLedger(path)
            try:
                cash, units = ledger.balances()
                self.assertEqual(cash, 80)
                self.assertEqual(units, 2)
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
