import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.durable_ledger import DurableLedger


class SQLiteIntegrityOnOpenTests(unittest.TestCase):

    def test_existing_database_checks_integrity_before_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            ledger = DurableLedger(path, "1000.00")
            ledger.close()

            observed = []
            real_connect = sqlite3.connect

            def traced_connect(*args, **kwargs):
                connection = real_connect(*args, **kwargs)
                connection.set_trace_callback(observed.append)
                return connection

            with patch(
                "ariyan_trading.durable_ledger.sqlite3.connect",
                side_effect=traced_connect,
            ):
                reopened = DurableLedger(path)
                reopened.close()

            statements = [
                statement.strip().upper()
                for statement in observed
            ]

            integrity_positions = [
                index
                for index, statement in enumerate(statements)
                if "PRAGMA INTEGRITY_CHECK" in statement
            ]

            transaction_positions = [
                index
                for index, statement in enumerate(statements)
                if statement.startswith("BEGIN IMMEDIATE")
            ]

            self.assertTrue(integrity_positions)
            self.assertTrue(transaction_positions)

            self.assertLess(
                integrity_positions[0],
                transaction_positions[0],
            )


if __name__ == "__main__":
    unittest.main()
