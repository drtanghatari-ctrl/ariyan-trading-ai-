import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableJournalTests(unittest.TestCase):

    def test_journal_exists_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "1000.00")
            ledger.close()

            reopened = DurableLedger(path)

            columns = {
                row[1]
                for row in reopened.db.execute(
                    "PRAGMA table_info(ledger_entries)"
                )
            }

            self.assertTrue({
                "sequence",
                "request_id",
                "action",
                "quantity",
                "price",
                "cash_delta",
                "units_delta",
            }.issubset(columns))

            count = reopened.db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]

            self.assertEqual(count, 0)
            reopened.close()

    def test_request_id_uniqueness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "1000.00")

            statement = (
                "INSERT INTO ledger_entries "
                "(request_id,action,quantity,price,"
                "cash_delta,units_delta) "
                "VALUES (?,?,?,?,?,?)"
            )

            ledger.db.execute(
                statement,
                ("r1", "BUY", "1", "10", "-10", "1"),
            )

            with self.assertRaises(sqlite3.IntegrityError):
                ledger.db.execute(
                    statement,
                    ("r1", "BUY", "1", "10", "-10", "1"),
                )

            ledger.close()


if __name__ == "__main__":
    unittest.main()
