"""A006-WB01 direct-writer boundary regression tests."""

import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class WriterBoundaryTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "ledger.sqlite"
        self.ledger = DurableLedger(
            self.database, opening_cash="1000.00"
        )

    def tearDown(self):
        self.ledger.close()
        self.temp.cleanup()

    def set_mode(self, mode):
        self.ledger.db.execute(
            "INSERT INTO ledger_meta(key,value) VALUES (?,?)",
            ("checkpoint_writer_mode", mode),
        )

    def count_entries(self):
        return self.ledger.db.execute(
            "SELECT COUNT(*) FROM ledger_entries"
        ).fetchone()[0]

    def test_legacy_direct_buy_remains_available(self):
        self.ledger.record_buy("legacy-buy", "1", "10")
        self.assertEqual(self.count_entries(), 1)

    def test_legacy_direct_sell_remains_available(self):
        self.ledger.record_buy("legacy-buy", "2", "10")
        self.ledger.record_sell("legacy-sell", "1", "10")
        self.assertEqual(self.count_entries(), 2)

    def test_managed_mode_rejects_buy(self):
        self.set_mode("managed-v1")

        with self.assertRaisesRegex(
            RuntimeError, "requires coordinator"
        ):
            self.ledger.record_buy(
                "blocked-buy", "1", "10"
            )

        self.assertEqual(self.count_entries(), 0)

    def test_managed_mode_rejects_sell(self):
        self.set_mode("managed-v1")

        with self.assertRaisesRegex(
            RuntimeError, "requires coordinator"
        ):
            self.ledger.record_sell(
                "blocked-sell", "1", "10"
            )

        self.assertEqual(self.count_entries(), 0)

    def test_unknown_mode_fails_closed(self):
        self.set_mode("unexpected-mode")

        with self.assertRaisesRegex(
            RuntimeError, "direct writes prohibited"
        ):
            self.ledger.record_buy(
                "blocked-unknown", "1", "10"
            )

        self.assertEqual(self.count_entries(), 0)


if __name__ == "__main__":
    unittest.main()
