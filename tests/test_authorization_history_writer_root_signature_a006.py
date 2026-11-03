"""A006 B4-B2A verification-only Ed25519 tests."""

import unittest
import uuid
from dataclasses import replace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)

from ariyan_trading.authorization_history_writer_authority import (
    VERSION,
    APPEND_HISTORY,
    HistoryWriterAuthorityEvidence,
)
from ariyan_trading.authorization_history_writer_authority_mac import (
    canonical_history_writer_authority_payload,
)
from ariyan_trading.authorization_history_writer_root_signature import (
    verify_history_writer_root_signature,
)


class HistoryWriterRootSignatureTests(unittest.TestCase):

    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        self.evidence = HistoryWriterAuthorityEvidence(
            version=VERSION,
            authorization_id=str(uuid.uuid4()),
            root_authority_id="human-root-1",
            writer_id="history-writer-1",
            stream_id=str(uuid.uuid4()),
            revision=1,
            allowed_operations=(APPEND_HISTORY,),
            valid_from=100,
            valid_until=200,
            status_reference="root-status-1",
        )

        self.payload = canonical_history_writer_authority_payload(
            self.evidence
        )
        self.signature = self.private.sign(self.payload)

    def test_valid_signature(self):
        self.assertTrue(
            verify_history_writer_root_signature(
                self.evidence, self.signature, self.public
            )
        )

    def test_wrong_public_key(self):
        other = Ed25519PrivateKey.generate()
        other_public = other.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        self.assertFalse(
            verify_history_writer_root_signature(
                self.evidence, self.signature, other_public
            )
        )

    def test_tampered_evidence(self):
        changed = replace(self.evidence, writer_id="other-writer")

        self.assertFalse(
            verify_history_writer_root_signature(
                changed, self.signature, self.public
            )
        )

    def test_tampered_signature(self):
        modified = bytearray(self.signature)
        modified[0] ^= 1

        self.assertFalse(
            verify_history_writer_root_signature(
                self.evidence, bytes(modified), self.public
            )
        )

    def test_invalid_signature_encoding(self):
        for value in (None, "signature", b"", b"x" * 63):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    verify_history_writer_root_signature(
                        self.evidence, value, self.public
                    )

    def test_invalid_public_key_encoding(self):
        for value in (None, "public", b"", b"x" * 31):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    verify_history_writer_root_signature(
                        self.evidence, self.signature, value
                    )

    def test_invalid_evidence(self):
        changed = replace(self.evidence, revision=0)

        with self.assertRaises(ValueError):
            verify_history_writer_root_signature(
                changed, self.signature, self.public
            )

    def test_signature_is_not_authority(self):
        self.assertTrue(
            verify_history_writer_root_signature(
                self.evidence, self.signature, self.public
            )
        )

        self.assertFalse(
            hasattr(self.evidence, "authorized")
        )


if __name__ == "__main__":
    unittest.main()
