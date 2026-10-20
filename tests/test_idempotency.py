from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.engine import PaperEngine


class IdempotencyTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "portfolio.sqlite"

    def test_duplicate_request_rejected(self):
        engine = PaperEngine(self.db)
        engine.execute("BUY", 100, request_id="order-001")

        with self.assertRaisesRegex(
            ValueError, "Duplicate trade request"
        ):
            engine.execute("BUY", 100, request_id="order-001")

        restarted = PaperEngine(self.db)
        self.assertAlmostEqual(restarted.cash, 9000)
        self.assertAlmostEqual(restarted.units, 10)

        with closing(sqlite3.connect(self.db)) as connection, connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM trades"
            ).fetchone()[0]

        self.assertEqual(count, 1)

    def test_duplicate_rejected_after_restart(self):
        first = PaperEngine(self.db)
        first.execute("BUY", 100, request_id="order-002")

        restarted = PaperEngine(self.db)
        with self.assertRaises(ValueError):
            restarted.execute(
                "BUY", 100, request_id="order-002"
            )

        self.assertAlmostEqual(restarted.cash, 9000)

    def test_existing_a002_database_migrates(self):
        with closing(sqlite3.connect(self.db)) as connection, connection:
            connection.execute("""
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    units REAL NOT NULL,
                    cash_after REAL NOT NULL
                )
            """)
            connection.execute("""
                INSERT INTO trades
                (action, price, units, cash_after)
                VALUES ('BUY', 100, 10, 9000)
            """)
            connection.execute("""
                CREATE TABLE portfolio (
                    id INTEGER PRIMARY KEY,
                    cash REAL NOT NULL,
                    units REAL NOT NULL
                )
            """)
            connection.execute(
                "INSERT INTO portfolio VALUES (1, 9000, 10)"
            )

        engine = PaperEngine(self.db)
        self.assertAlmostEqual(engine.cash, 9000)
        self.assertAlmostEqual(engine.units, 10)

        engine.execute("BUY", 100, request_id="new-003")

        with closing(sqlite3.connect(self.db)) as connection, connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM trades"
            ).fetchone()[0]
            new_id = connection.execute(
                "SELECT request_id FROM trades WHERE id=2"
            ).fetchone()[0]

        self.assertEqual(count, 2)
        self.assertEqual(new_id, "new-003")


if __name__ == "__main__":
    unittest.main()
