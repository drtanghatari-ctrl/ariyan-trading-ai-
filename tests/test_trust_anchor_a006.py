import json
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.trust_anchor import (
    create_anchor,
    verify_anchor,
    write_anchor,
    read_anchor,
)


class TrustAnchorA006Tests(unittest.TestCase):

    def setUp(self):
        self.key = b"K" * 32
        self.digest = "ab" * 32

    def test_valid_anchor(self):
        anchor = create_anchor(3, self.digest, self.key)
        self.assertEqual(
            verify_anchor(anchor, self.key),
            (3, self.digest),
        )

    def test_deterministic_authentication(self):
        a = create_anchor(3, self.digest, self.key)
        b = create_anchor(3, self.digest, self.key)
        self.assertEqual(a, b)

    def test_modified_sequence_rejected(self):
        anchor = create_anchor(3, self.digest, self.key)
        anchor["sequence"] = 2
        with self.assertRaises(ValueError):
            verify_anchor(anchor, self.key)

    def test_modified_digest_rejected(self):
        anchor = create_anchor(3, self.digest, self.key)
        anchor["digest"] = "cd" * 32
        with self.assertRaises(ValueError):
            verify_anchor(anchor, self.key)

    def test_wrong_key_rejected(self):
        anchor = create_anchor(3, self.digest, self.key)
        with self.assertRaises(ValueError):
            verify_anchor(anchor, b"Z" * 32)

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValueError):
            create_anchor(3, self.digest, b"short")

    def test_boolean_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_anchor(True, self.digest, self.key)

    def test_negative_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_anchor(-1, self.digest, self.key)

    def test_invalid_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_anchor(1, "not-a-digest", self.key)

    def test_extra_field_rejected(self):
        anchor = create_anchor(3, self.digest, self.key)
        anchor["unexpected"] = "value"
        with self.assertRaises(ValueError):
            verify_anchor(anchor, self.key)

    def test_disk_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchor.json"
            anchor = create_anchor(3, self.digest, self.key)
            write_anchor(path, anchor, self.key)
            self.assertEqual(
                read_anchor(path, self.key),
                (3, self.digest),
            )

    def test_disk_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchor.json"
            anchor = create_anchor(3, self.digest, self.key)
            write_anchor(path, anchor, self.key)

            altered = json.loads(path.read_text())
            altered["sequence"] = 1
            path.write_text(json.dumps(altered))

            with self.assertRaises(ValueError):
                read_anchor(path, self.key)

    def test_oversized_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "anchor.json"
            path.write_bytes(b"X" * 5000)

            with self.assertRaises(ValueError):
                read_anchor(path, self.key)


if __name__ == "__main__":
    unittest.main()
