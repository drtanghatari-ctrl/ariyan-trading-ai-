"""Additional A006 C2D history-anchor security tests."""

import hashlib
import hmac
import unittest
import uuid

from ariyan_trading.authorization_history_anchor import (
    DOMAIN,
    create_history_anchor,
    verify_history_anchor,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
)
from ariyan_trading.trust_anchor import create_anchor


class HistoryAnchorHardeningTests(unittest.TestCase):

    def setUp(self):
        self.stream_id = str(uuid.uuid4())
        self.digest = opening_history_commitment(self.stream_id)
        self.key = b"K" * 32

    def anchor(self):
        return create_history_anchor(
            self.stream_id, 0, self.digest, self.key
        )

    def test_negative_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id, -1, self.digest, self.key
            )

    def test_float_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id, 1.0, self.digest, self.key
            )

    def test_nonbytes_key_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id, 0, self.digest, "K" * 32
            )

    def test_uppercase_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id, 0, self.digest.upper(), self.key
            )

    def test_uppercase_mac_rejected(self):
        anchor = self.anchor()
        anchor["mac"] = anchor["mac"].upper()

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_malformed_mac_rejected(self):
        anchor = self.anchor()
        anchor["mac"] = "z" * 64

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_boolean_mac_rejected(self):
        anchor = self.anchor()
        anchor["mac"] = True

        with self.assertRaises(ValueError):
            verify_history_anchor(anchor, self.key)

    def test_noncanonical_stream_rejected(self):
        with self.assertRaises(ValueError):
            create_history_anchor(
                self.stream_id.upper(),
                0,
                self.digest,
                self.key,
            )

    def test_financial_anchor_mac_not_interchangeable(self):
        history = self.anchor()
        financial = create_anchor(0, self.digest, self.key)

        self.assertNotEqual(history["mac"], financial["mac"])

        substituted = dict(history)
        substituted["mac"] = financial["mac"]

        with self.assertRaises(ValueError):
            verify_history_anchor(substituted, self.key)

    def test_domain_separator_is_explicit(self):
        self.assertEqual(
            DOMAIN,
            b"ARIYAN-A006-AUTH-HISTORY-ANCHOR-V1" + bytes([0]),
        )


if __name__ == "__main__":
    unittest.main()
