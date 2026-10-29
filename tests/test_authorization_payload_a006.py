import unittest
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AuthorizationEvidence,
    AUTHORIZATION_EVIDENCE_VERSION,
)
from ariyan_trading.authorization_payload import (
    canonical_authorization_payload as encode,
    DOMAIN,
)


class AuthorizationPayloadTests(unittest.TestCase):

    def setUp(self):
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

    def test_deterministic(self):
        self.assertEqual(encode(self.e), encode(self.e))
        self.assertTrue(encode(self.e).startswith(DOMAIN))

    def test_operation_order_canonical(self):
        other = replace(
            self.e,
            allowed_operations=("SELL", "BUY"),
        )
        self.assertEqual(encode(self.e), encode(other))

    def test_mutation_changes_payload(self):
        variants = (
            replace(self.e, revision=2),
            replace(self.e, writer_id="writer-002"),
            replace(self.e, allowed_operations=("BUY",)),
            replace(self.e, valid_until=201),
        )
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertNotEqual(encode(self.e), encode(changed))

    def test_invalid_evidence_rejected(self):
        invalid = replace(self.e, revision=0)
        with self.assertRaises(ValueError):
            encode(invalid)


if __name__ == "__main__":
    unittest.main()
