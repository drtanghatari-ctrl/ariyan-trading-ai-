import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class JournalTamperingA005Tests(unittest.TestCase):

    def test_consistent_transaction_rewrite_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tampered.sqlite"

            ledger = DurableLedger(path, "100.00")
            try:
                ledger.record_buy("original-buy", "2", "10")
            finally:
                ledger.close()

            with closing(sqlite3.connect(path)) as db, db:
                db.execute(
                    "UPDATE ledger_entries "
                    "SET quantity='1', "
                    "cash_delta='-10', "
                    "units_delta='1' "
                    "WHERE request_id='original-buy'"
                )
                db.commit()

                self.assertEqual(
                    db.execute(
                        "PRAGMA integrity_check"
                    ).fetchall(),
                    [("ok",)],
                )

            # A protected journal must reject this alteration.
            with self.assertRaises(ValueError):
                reopened = DurableLedger(path)
                reopened.close()


if __name__ == "__main__":
    unittest.main()
