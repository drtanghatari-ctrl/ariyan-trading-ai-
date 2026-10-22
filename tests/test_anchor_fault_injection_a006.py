"""A006 anchor publication fault-injection tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.trust_anchor import (
    create_anchor,
    read_anchor,
    write_anchor,
)


class AnchorFaultInjectionA006Tests(unittest.TestCase):

    def test_replace_failure_preserves_existing_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "anchor.json"
            key = b"A" * 32

            old_digest = "a" * 64
            new_digest = "b" * 64

            write_anchor(
                path, create_anchor(1, old_digest, key), key
            )
            original_bytes = path.read_bytes()

            with patch(
                "ariyan_trading.trust_anchor.os.replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(
                    OSError, "injected replace failure"
                ):
                    write_anchor(
                        path,
                        create_anchor(2, new_digest, key),
                        key,
                    )

            self.assertEqual(
                path.read_bytes(), original_bytes
            )
            self.assertEqual(
                read_anchor(path, key), (1, old_digest)
            )
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["anchor.json"],
            )


    def test_directory_fsync_failure_after_replace(self):
        import os
        import stat

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "anchor.json"
            key = b"A" * 32

            old_digest = "a" * 64
            new_digest = "b" * 64

            write_anchor(
                path, create_anchor(1, old_digest, key), key
            )
            original_bytes = path.read_bytes()

            real_fsync = os.fsync
            directory_fsync_attempted = []

            def injected_fsync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    directory_fsync_attempted.append(True)
                    raise OSError("injected directory fsync failure")
                return real_fsync(fd)

            with patch(
                "ariyan_trading.trust_anchor.os.fsync",
                side_effect=injected_fsync,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected directory fsync failure"
                ):
                    write_anchor(
                        path,
                        create_anchor(2, new_digest, key),
                        key,
                    )

            self.assertTrue(directory_fsync_attempted)
            self.assertNotEqual(
                path.read_bytes(), original_bytes
            )
            self.assertEqual(
                read_anchor(path, key), (2, new_digest)
            )
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["anchor.json"],
            )


if __name__ == "__main__":
    unittest.main()
