import tempfile
import threading
import unittest
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger


class DurableFirstOpenTests(unittest.TestCase):

    def test_concurrent_first_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            barrier = threading.Barrier(2)
            results = []
            lock = threading.Lock()

            def worker():
                try:
                    barrier.wait(timeout=5)
                    ledger = DurableLedger(path, "100.00")
                    ledger.close()
                    outcome = "success"
                except Exception as exc:
                    outcome = type(exc).__name__

                with lock:
                    results.append(outcome)

            threads = [
                threading.Thread(target=worker)
                for _ in range(2)
            ]

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive())

            self.assertEqual(
                results.count("success"), 2,
                results,
            )

            reopened = DurableLedger(path)
            self.assertEqual(
                str(reopened.opening_cash), "100.00"
            )
            reopened.close()


if __name__ == "__main__":
    unittest.main()
