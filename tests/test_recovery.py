from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.engine import PaperEngine


class RecoveryTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "portfolio.sqlite"

    def test_restart_recovers_balances(self):
        first = PaperEngine(self.path)
        first.execute("BUY", 100)

        restarted = PaperEngine(self.path)
        self.assertAlmostEqual(restarted.cash, 9000)
        self.assertAlmostEqual(restarted.units, 10)

    def test_restart_does_not_reset_capital(self):
        first = PaperEngine(self.path)
        first.execute("BUY", 100)

        restarted = PaperEngine(self.path, cash=999999)
        self.assertAlmostEqual(restarted.cash, 9000)

    def test_sequential_instances_use_latest_state(self):
        first = PaperEngine(self.path)
        second = PaperEngine(self.path)

        first.execute("BUY", 100)
        second.execute("BUY", 100)

        restarted = PaperEngine(self.path)
        self.assertAlmostEqual(restarted.cash, 8000)
        self.assertAlmostEqual(restarted.units, 20)

    def test_failed_insert_rolls_back_portfolio(self):
        engine = PaperEngine(self.path)

        with closing(sqlite3.connect(self.path)) as db:
            db.execute("""
                CREATE TRIGGER reject_trade
                BEFORE INSERT ON trades
                BEGIN
                    SELECT RAISE(ABORT, 'forced failure');
                END
            """)

        with self.assertRaises(sqlite3.IntegrityError):
            engine.execute("BUY", 100)

        restarted = PaperEngine(self.path)
        self.assertAlmostEqual(restarted.cash, 10000)
        self.assertAlmostEqual(restarted.units, 0)

    def test_invalid_order_does_not_change_state(self):
        engine = PaperEngine(self.path)

        with self.assertRaises(ValueError):
            engine.execute("BUY", float("nan"))

        restarted = PaperEngine(self.path)
        self.assertAlmostEqual(restarted.cash, 10000)
        self.assertAlmostEqual(restarted.units, 0)

    def test_trade_and_portfolio_persist_together(self):
        engine = PaperEngine(self.path)
        engine.execute("BUY", 100)

        with closing(sqlite3.connect(self.path)) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM trades"
            ).fetchone()[0]
            cash = db.execute(
                "SELECT cash FROM portfolio WHERE id=1"
            ).fetchone()[0]

        self.assertEqual(count, 1)
        self.assertAlmostEqual(cash, 9000)


if __name__ == "__main__":
    unittest.main()
