import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.schema_validation import (
    validate_ledger_schema,
)


class SchemaValidationTests(unittest.TestCase):

    def test_valid_schema_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "valid.sqlite"
            ledger = DurableLedger(path, "100.00")
            ledger.close()

            db = sqlite3.connect(path)
            try:
                validate_ledger_schema(db)
            finally:
                db.close()

    def test_malformed_schemas_rejected(self):
        cases = {
            "missing_metadata_primary_key": [
                "CREATE TABLE ledger_meta "
                "(key TEXT, value TEXT)",
                "CREATE TABLE ledger_entries "
                "(sequence INTEGER)"
            ],
            "missing_journal_columns": [
                "CREATE TABLE ledger_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE ledger_entries "
                "(sequence INTEGER)"
            ],
            "missing_request_id_uniqueness": [
                "CREATE TABLE ledger_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
                "CREATE TABLE ledger_entries ("
                "sequence INTEGER PRIMARY KEY AUTOINCREMENT,"
                "request_id TEXT NOT NULL,"
                "action TEXT NOT NULL,"
                "quantity TEXT NOT NULL,"
                "price TEXT NOT NULL,"
                "cash_delta TEXT NOT NULL,"
                "units_delta TEXT NOT NULL)"
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            for name, statements in cases.items():
                with self.subTest(name=name):
                    path = Path(directory) / f"{name}.sqlite"
                    db = sqlite3.connect(path)

                    try:
                        for statement in statements:
                            db.execute(statement)
                        db.commit()

                        with self.assertRaises(ValueError):
                            validate_ledger_schema(db)
                    finally:
                        db.close()


if __name__ == "__main__":
    unittest.main()
