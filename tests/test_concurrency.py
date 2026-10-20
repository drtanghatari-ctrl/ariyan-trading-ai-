from contextlib import closing
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ariyan_trading.engine import PaperEngine


class ConcurrencyTests(unittest.TestCase):

    def test_same_request_from_two_instances(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "concurrent.sqlite"

            def submit():
                engine = PaperEngine(path)
                try:
                    engine.execute(
                        "BUY", 100,
                        request_id="concurrent-order-001",
                    )
                    return "executed"
                except ValueError as exc:
                    if str(exc) == "Duplicate trade request":
                        return "duplicate"
                    raise

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(
                    lambda _: submit(), range(2)
                ))

            self.assertCountEqual(
                outcomes, ["executed", "duplicate"]
            )

            recovered = PaperEngine(path)
            self.assertAlmostEqual(recovered.cash, 9000)
            self.assertAlmostEqual(recovered.units, 10)

            with closing(sqlite3.connect(path)) as db:
                count = db.execute(
                    "SELECT COUNT(*) FROM trades"
                ).fetchone()[0]

            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
