"""A006 C2D authorization-history anchor regression tests."""

import unittest
import uuid

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
    verify_history_anchor,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
)


class AuthorizationHistoryAnchorTests(unittest.TestCase):

    def setUp(self):
        self.stream_id = str(uuid.uuid4())
        self.digest = opening_history_commitment(self.stream_id)
        self.key = b"A" * 32

    def anchor(self):
        return create_history_anchor(
            self.stream_id,
            0,
            self.digest,
            self.key,
        )

    def test_valid_anchor(self):
        self.assertEqual(
            verify_history_anchor(self.anchor(), self.key),
            (self.stream_id, 0, self.digest),
        )

    def test_wrong_key_rejected(self):
        with self.assertRaises(ValueError):
            verify_history_anchor(self.anchor(), b"B" * 32)

    def test_short_key_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id, 0, self.digest, b"A" * 31
            )

    def test_modified_sequence_rejected(self):
        anchor = self.anchor()
        anchor["history_sequence"] = 1

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_modified_digest_rejected(self):
        anchor = self.anchor()
        anchor["history_digest"] = "0" * 64

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_modified_stream_rejected(self):
        anchor = self.anchor()
        anchor["stream_id"] = str(uuid.uuid4())

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_extra_field_rejected(self):
        anchor = self.anchor()
        anchor["unexpected"] = True

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_missing_field_rejected(self):
        anchor = self.anchor()
        del anchor["mac"]

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_noncanonical_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id,
                0,
                "ABCDEF" * 10 + "ABCD",
                self.key,
            )

    def test_boolean_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id,
                True,
                self.digest,
                self.key,
            )

    def test_cross_stream_anchor_rejected(self):
        first = self.anchor()

        second_stream = str(uuid.uuid4())
        second_digest = opening_history_commitment(second_stream)

        second = create_history_anchor(
            second_stream,
            0,
            second_digest,
            self.key,
        )

        self.assertNotEqual(first["mac"], second["mac"])

    def test_deterministic_authentication(self):
        self.assertEqual(self.anchor(), self.anchor())


if __name__ == "__main__":
    unittest.main()
