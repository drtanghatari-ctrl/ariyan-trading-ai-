"""Concurrent initialization and schema integrity tests."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

from ariyan_trading.engine import PaperEngine


class AtomicInitializationTests(unittest.TestCase):

    def test_eight_simultaneous_initializers(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shared.sqlite"
            barrier = Barrier(8)

            def initialize(_):
                barrier.wait(timeout=10)
                engine = PaperEngine(path)
                return engine.cash, engine.units

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(initialize, range(8)))

            self.assertEqual(
                results,
                [(10000.0, 0.0)] * 8,
            )

            with closing(sqlite3.connect(path)) as db:
                portfolios = db.execute(
                    "SELECT COUNT(*) FROM portfolio"
                ).fetchone()[0]

                columns = {
                    row[1] for row in db.execute(
                        "PRAGMA table_info(trades)"
                    )
                }

                indexes = {
                    row[1] for row in db.execute(
                        "PRAGMA index_list(trades)"
                    )
                }

            self.assertEqual(portfolios, 1)
            self.assertIn("request_id", columns)
            self.assertIn("idx_trades_request_id", indexes)


if __name__ == "__main__":
    unittest.main()
