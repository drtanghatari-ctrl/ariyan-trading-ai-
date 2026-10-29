"""A006 P3C12-B4 authorization evidence model tests."""

import unittest
from dataclasses import FrozenInstanceError

from ariyan_trading.authorization_evidence import (
    AUTHORIZATION_EVIDENCE_VERSION,
    AuthorizationEvidence,
)


class AuthorizationEvidenceTests(unittest.TestCase):

    def make_evidence(self):
        return AuthorizationEvidence(
            version=AUTHORIZATION_EVIDENCE_VERSION,
            authorization_id="grant-001",
            ledger_id="ledger-001",
            writer_id="writer-001",
            authority_id="authority-001",
            revision=1,
            allowed_operations=("BUY", "SELL"),
            valid_from=100,
            valid_until=200,
        )

    def test_model_preserves_fields(self):
        evidence = self.make_evidence()

        self.assertEqual(
            evidence.allowed_operations,
            ("BUY", "SELL"),
        )
        self.assertEqual(evidence.revision, 1)

    def test_model_is_frozen(self):
        evidence = self.make_evidence()

        with self.assertRaises(FrozenInstanceError):
            evidence.revision = 2

    def test_version_constant(self):
        self.assertEqual(
            AUTHORIZATION_EVIDENCE_VERSION,
            "ARIYAN-A006-AUTHORIZATION-EVIDENCE-V1",
        )


if __name__ == "__main__":
    unittest.main()
