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


class AuthorizationMACTests(unittest.TestCase):

    def setUp(self):
        self.key = b"A" * 32
        self.other_key = b"B" * 32

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

    def test_valid_mac(self):
        mac = create_authorization_mac(self.e, self.key)
        self.assertTrue(
            verify_authorization_mac(self.e, mac, self.key)
        )

    def test_wrong_key(self):
        mac = create_authorization_mac(self.e, self.key)
        self.assertFalse(
            verify_authorization_mac(self.e, mac, self.other_key)
        )

    def test_tampered_evidence(self):
        mac = create_authorization_mac(self.e, self.key)

        changes = (
            replace(self.e, revision=2),
            replace(self.e, writer_id="writer-002"),
            replace(self.e, authority_id="authority-002"),
            replace(self.e, allowed_operations=("BUY",)),
            replace(self.e, valid_until=201),
        )

        for changed in changes:
            with self.subTest(changed=changed):
                self.assertFalse(
                    verify_authorization_mac(
                        changed, mac, self.key
                    )
                )

    def test_invalid_mac_encoding(self):
        for mac in ("", "0" * 63, "Z" * 64, "A" * 64):
            with self.subTest(mac=mac):
                with self.assertRaises(ValueError):
                    verify_authorization_mac(
                        self.e, mac, self.key
                    )

    def test_short_key_rejected(self):
        with self.assertRaises(ValueError):
            create_authorization_mac(
                self.e, b"short"
            )

    def test_canonical_operation_order(self):
        mac = create_authorization_mac(self.e, self.key)

        reordered = replace(
            self.e,
            allowed_operations=("SELL", "BUY"),
        )

        self.assertTrue(
            verify_authorization_mac(
                reordered, mac, self.key
            )
        )


if __name__ == "__main__":
    unittest.main()
