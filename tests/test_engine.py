from contextlib import closing
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.engine import (
    PaperEngine,
    RiskLimits,
    signal,
    validate_prices,
)


class EngineTests(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "test.sqlite"

    def test_buy_signal(self):
        self.assertEqual(
            signal([100, 101, 102, 103, 104]),
            "BUY"
        )

    def test_sell_signal(self):
        self.assertEqual(
            signal([104, 103, 102, 101, 100]),
            "SELL"
        )

    def test_invalid_prices(self):
        for prices in (
            [1, 2, 3, 4, -5],
            [1, 2, 3, 4, float("nan")],
        ):
            with self.assertRaises(ValueError):
                validate_prices(prices)

    def test_buy_and_sell(self):
        engine = PaperEngine(self.db)
        buy = engine.execute("BUY", 100)
        self.assertIsNotNone(buy)
        self.assertAlmostEqual(engine.cash, 9000)
        self.assertAlmostEqual(engine.units, 10)

        sell = engine.execute("SELL", 110)
        self.assertIsNotNone(sell)
        self.assertAlmostEqual(engine.cash, 10100)
        self.assertEqual(engine.units, 0)

    def test_risk_limit(self):
        engine = PaperEngine(
            self.db,
            limits=RiskLimits(
                max_trade_fraction=0.05,
                max_position_fraction=0.10,
            ),
        )
        engine.execute("BUY", 100)
        self.assertAlmostEqual(engine.cash, 9500)

    def test_trade_persistence(self):
        engine = PaperEngine(self.db)
        engine.execute("BUY", 100)

        with closing(sqlite3.connect(self.db)) as db:
            count = db.execute(
                "SELECT COUNT(*) FROM trades"
            ).fetchone()[0]

        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
