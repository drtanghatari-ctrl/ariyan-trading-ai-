"""Cross-platform process-level initialization lock."""

import os
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def initialization_lock(database_path, timeout=15):
    """Serialize database initialization across processes."""
    path = Path(str(database_path) + ".init.lock")
    deadline = time.monotonic() + timeout

    if os.name == "nt":
        import msvcrt

        handle = open(path, "a+b")
        try:
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(
                        handle.fileno(),
                        msvcrt.LK_NBLCK,
                        1,
                    )
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Database initialization lock timeout"
                        )
                    time.sleep(0.025)

            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(
                    handle.fileno(),
                    msvcrt.LK_UNLCK,
                    1,
                )
        finally:
            handle.close()

    else:
        import fcntl

        handle = open(path, "a+b")
        try:
            while True:
                try:
                    fcntl.flock(
                        handle.fileno(),
                        fcntl.LOCK_EX | fcntl.LOCK_NB,
                    )
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Database initialization lock timeout"
                        )
                    time.sleep(0.025)

            try:
                yield
            finally:
                fcntl.flock(
                    handle.fileno(),
                    fcntl.LOCK_UN,
                )
        finally:
            handle.close()
