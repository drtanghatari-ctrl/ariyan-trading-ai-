import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableSchemaIntegrityTests(unittest.TestCase):

    def test_missing_journal_must_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "100.00")
            ledger.record_buy("buy-1", "1", "10")
            ledger.close()

            with closing(sqlite3.connect(path)) as db, db:
                db.execute("DROP TABLE ledger_entries")

            with self.assertRaises(ValueError):
                reopened = DurableLedger(path)
                reopened.close()


if __name__ == "__main__":
    unittest.main()
