import hashlib
import hmac
import unittest
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AuthorizationEvidence,
    AUTHORIZATION_EVIDENCE_VERSION,
)
from ariyan_trading.authorization_mac import (
    create_authorization_mac,
    verify_authorization_mac,
)
from ariyan_trading.authorization_payload import (
    canonical_authorization_payload,
)


class AuthorizationMACHardeningTests(unittest.TestCase):

    def setUp(self):
        self.key = b"K" * 32
        self.e = AuthorizationEvidence(
            AUTHORIZATION_EVIDENCE_VERSION,
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
            "writer-001",
            "authority-001",
            1,
            ("BUY", "SELL"),
            100,
            200,
        )

    def test_identifier_substitution(self):
        mac = create_authorization_mac(self.e, self.key)

        changes = (
            replace(
                self.e,
                authorization_id="123e4567-e89b-42d3-a456-426614174002",
            ),
            replace(
                self.e,
                ledger_id="123e4567-e89b-42d3-a456-426614174003",
            ),
        )

        for changed in changes:
            with self.subTest(changed=changed):
                self.assertFalse(
                    verify_authorization_mac(
                        changed, mac, self.key
                    )
                )

    def test_invalid_evidence_rejected(self):
        invalid = replace(self.e, revision=0)

        with self.assertRaises(ValueError):
            create_authorization_mac(invalid, self.key)

        mac = create_authorization_mac(self.e, self.key)

        with self.assertRaises(ValueError):
            verify_authorization_mac(
                invalid, mac, self.key
            )

    def test_invalid_key_types(self):
        for key in (None, "K" * 32, bytearray(32), b""):
            with self.subTest(key_type=type(key).__name__):
                with self.assertRaises(ValueError):
                    create_authorization_mac(self.e, key)

    def test_cross_domain_substitution(self):
        payload = canonical_authorization_payload(self.e)

        foreign_payload = (
            b"ARIYAN-A006-WRITER-POLICY-V1\x00"
            + payload.split(b"\x00", 1)[1]
        )

        foreign_mac = hmac.new(
            self.key,
            foreign_payload,
            hashlib.sha256,
        ).hexdigest()

        self.assertFalse(
            verify_authorization_mac(
                self.e, foreign_mac, self.key
            )
        )

    def test_wrong_tag_same_length(self):
        mac = create_authorization_mac(self.e, self.key)

        changed = (
            ("0" if mac[0] != "0" else "1")
            + mac[1:]
        )

        self.assertFalse(
            verify_authorization_mac(
                self.e, changed, self.key
            )
        )


if __name__ == "__main__":
    unittest.main()
