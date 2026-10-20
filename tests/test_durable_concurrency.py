import tempfile
import threading
import unittest
from decimal import Decimal
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableConcurrencyTests(unittest.TestCase):

    def test_competing_buys_cannot_overspend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            initial = DurableLedger(path, "100.00")
            initial.close()

            barrier = threading.Barrier(2)
            outcomes = []
            lock = threading.Lock()

            def worker(request_id):
                ledger = DurableLedger(path)
                try:
                    barrier.wait(timeout=5)
                    ledger.record_buy(
                        request_id, "1", "80.00"
                    )
                    result = "success"
                except ValueError:
                    result = "rejected"
                finally:
                    ledger.close()

                with lock:
                    outcomes.append(result)

            threads = [
                threading.Thread(
                    target=worker,
                    args=(f"buy-{i}",),
                )
                for i in range(2)
            ]

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())

            self.assertEqual(
                sorted(outcomes),
                ["rejected", "success"],
            )

            reopened = DurableLedger(path)
            self.assertEqual(
                reopened.balances(),
                (Decimal("20.00"), Decimal("1")),
            )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
