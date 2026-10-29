"""A006 C2D-04A history-anchor filesystem tests."""

import json
import os
import stat
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_anchor_io import (
    read_history_anchor,
    write_history_anchor,
)


class HistoryAnchorIOTests(unittest.TestCase):

    def setUp(self):
        self.key = b"H" * 32
        self.stream_id = str(uuid.uuid4())
        self.digest = "a" * 64

    def anchor(self, sequence=0, digest=None):
        return create_history_anchor(
            self.stream_id,
            sequence,
            self.digest if digest is None else digest,
            self.key,
        )

    def test_disk_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            anchor = self.anchor()

            write_history_anchor(path, anchor, self.key)

            self.assertEqual(
                read_history_anchor(path, self.key),
                (self.stream_id, 0, self.digest),
            )

    def test_wrong_key_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"

            write_history_anchor(
                path, self.anchor(), self.key
            )

            with self.assertRaises(ValueError):
                read_history_anchor(path, b"W" * 32)

    def test_disk_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"

            write_history_anchor(
                path, self.anchor(), self.key
            )

            altered = json.loads(path.read_text())
            altered["history_sequence"] = 1
            path.write_text(json.dumps(altered))

            with self.assertRaises(ValueError):
                read_history_anchor(path, self.key)

    def test_oversized_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            path.write_bytes(b"X" * 5000)

            with self.assertRaises(ValueError):
                read_history_anchor(path, self.key)

    def test_missing_directory_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = (
                Path(directory)
                / "missing"
                / "history.json"
            )

            with self.assertRaises(FileNotFoundError):
                write_history_anchor(
                    path, self.anchor(), self.key
                )

    def test_replace_failure_preserves_old_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.json"

            old = self.anchor()
            new = self.anchor(1, "b" * 64)

            write_history_anchor(path, old, self.key)
            original = path.read_bytes()

            with patch(
                "ariyan_trading.authorization_history_anchor_io.os.replace",
                side_effect=OSError("injected replace failure"),
            ):
                with self.assertRaisesRegex(
                    OSError, "injected replace failure"
                ):
                    write_history_anchor(
                        path, new, self.key
                    )

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(
                read_history_anchor(path, self.key),
                (self.stream_id, 0, self.digest),
            )
            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["history.json"],
            )

    def test_directory_fsync_failure_is_ambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "history.json"

            write_history_anchor(
                path, self.anchor(), self.key
            )

            real_fsync = os.fsync
            directory_fsync_attempted = []

            def injected_fsync(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    directory_fsync_attempted.append(True)
                    raise OSError(
                        "injected directory fsync failure"
                    )
                return real_fsync(fd)

            with patch(
                "ariyan_trading.authorization_history_anchor_io.os.fsync",
                side_effect=injected_fsync,
            ):
                with self.assertRaisesRegex(
                    OSError, "injected directory fsync failure"
                ):
                    write_history_anchor(
                        path,
                        self.anchor(1, "b" * 64),
                        self.key,
                    )

            self.assertTrue(directory_fsync_attempted)

            # Replacement occurred, but durable publication
            # cannot be inferred after the injected failure.
            self.assertEqual(
                read_history_anchor(path, self.key),
                (self.stream_id, 1, "b" * 64),
            )

            self.assertEqual(
                sorted(p.name for p in root.iterdir()),
                ["history.json"],
            )


if __name__ == "__main__":
    unittest.main()
