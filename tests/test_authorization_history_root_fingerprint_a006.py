"""A006 B4-B2C fingerprint matching tests."""

import hashlib
import unittest
from dataclasses import replace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from ariyan_trading.authorization_history_root_binding import (
    VERSION,
    ALGORITHM,
    HistoryRootBinding,
)
from ariyan_trading.authorization_history_root_fingerprint import (
    matches_history_root_fingerprint,
)


class HistoryRootFingerprintTests(unittest.TestCase):

    def setUp(self):
        private = Ed25519PrivateKey.generate()
        self.public_key = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        self.binding = HistoryRootBinding(
            version=VERSION,
            root_authority_id="human-root-1",
            algorithm=ALGORITHM,
            public_key_sha256=hashlib.sha256(
                self.public_key
            ).hexdigest(),
            enrollment_revision=1,
            trust_reference="external-enrollment-1",
        )

    def test_matching_key(self):
        self.assertTrue(matches_history_root_fingerprint(
            self.binding, self.public_key
        ))

    def test_different_key(self):
        other = Ed25519PrivateKey.generate()
        other_public = other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.assertFalse(matches_history_root_fingerprint(
            self.binding, other_public
        ))

    def test_modified_fingerprint(self):
        changed = replace(
            self.binding,
            public_key_sha256="0" * 64,
        )
        self.assertFalse(matches_history_root_fingerprint(
            changed, self.public_key
        ))

    def test_invalid_binding(self):
        changed = replace(self.binding, enrollment_revision=0)
        with self.assertRaises(ValueError):
            matches_history_root_fingerprint(
                changed, self.public_key
            )

    def test_invalid_key_encoding(self):
        for key in (None, "", b"", b"x" * 31, b"x" * 33):
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    matches_history_root_fingerprint(
                        self.binding, key
                    )

    def test_match_does_not_grant_authority(self):
        self.assertTrue(matches_history_root_fingerprint(
            self.binding, self.public_key
        ))
        self.assertFalse(hasattr(self.binding, "trusted"))
        self.assertFalse(hasattr(self.binding, "authorized"))


if __name__ == "__main__":
    unittest.main()
