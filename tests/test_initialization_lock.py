import tempfile
import threading
import time
import unittest
from pathlib import Path

from ariyan_trading.initialization_lock import (
    initialization_lock,
)


class InitializationLockTests(unittest.TestCase):

    def test_lock_serializes_threads(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            active = 0
            maximum_active = 0
            guard = threading.Lock()
            errors = []

            def worker():
                nonlocal active, maximum_active
                try:
                    with initialization_lock(path):
                        with guard:
                            active += 1
                            maximum_active = max(
                                maximum_active, active
                            )

                        time.sleep(0.02)

                        with guard:
                            active -= 1
                except Exception as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=worker)
                for _ in range(4)
            ]

            for thread in threads:
                thread.start()

            for thread in threads:
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

            self.assertEqual(errors, [])
            self.assertEqual(maximum_active, 1)

    def test_lock_released_after_exception(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.sqlite"

            with self.assertRaises(RuntimeError):
                with initialization_lock(path):
                    raise RuntimeError("Simulated failure")

            with initialization_lock(path):
                pass


if __name__ == "__main__":
    unittest.main()
