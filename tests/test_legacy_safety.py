import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from ariyan_trading.engine import PaperEngine


class LegacySafetyTests(unittest.TestCase):

    def test_historical_trades_without_portfolio_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite"

            with closing(sqlite3.connect(path)) as db, db:
                db.execute("""
                    CREATE TABLE trades (
                        id INTEGER PRIMARY KEY,
                        action TEXT NOT NULL,
                        price REAL NOT NULL,
                        units REAL NOT NULL,
                        cash_after REAL NOT NULL
                    )
                """)
                db.execute("""
                    INSERT INTO trades
                    (action, price, units, cash_after)
                    VALUES ('BUY', 100, 10, 9000)
                """)

            with self.assertRaisesRegex(
                RuntimeError, "manual recovery required"
            ):
                PaperEngine(path)

            with closing(sqlite3.connect(path)) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM trades"
                ).fetchone()[0]
                exists = db.execute(
                    "SELECT COUNT(*) FROM sqlite_master "
                    "WHERE type='table' AND name='portfolio'"
                ).fetchone()[0]

                portfolio = (
                    db.execute(
                        "SELECT COUNT(*) FROM portfolio"
                    ).fetchone()[0]
                    if exists else 0
                )

            self.assertEqual(count, 1)
            self.assertEqual(portfolio, 0)


if __name__ == "__main__":
    unittest.main()
