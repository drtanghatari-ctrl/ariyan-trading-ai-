import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AUTHORIZATION_EVIDENCE_VERSION,
    AuthorizationEvidence,
)
from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_assessment import (
    assess_authorization,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus,
)


class AuthorizationAssessmentTests(unittest.TestCase):

    def setUp(self):
        self.evidence = AuthorizationEvidence(
            version=AUTHORIZATION_EVIDENCE_VERSION,
            authorization_id=str(uuid.uuid4()),
            ledger_id=str(uuid.uuid4()),
            writer_id="writer-1",
            authority_id="authority-1",
            revision=1,
            allowed_operations=("BUY", "SELL"),
            valid_from=100,
            valid_until=200,
        )

        self.status = AuthorizationStatusRecord(
            authorization_id=self.evidence.authorization_id,
            authority_id=self.evidence.authority_id,
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

    def assess(self, evidence=None, status=None, operation="BUY"):
        return assess_authorization(
            evidence=self.evidence if evidence is None else evidence,
            status_record=self.status if status is None else status,
            operation=operation,
        )

    def test_active_never_allows(self):
        result = self.assess()
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.UNCERTAIN,
        )

    def test_all_statuses_never_allow(self):
        for state in AuthorizationStatus:
            with self.subTest(state=state):
                result = self.assess(
                    status=replace(self.status, status=state)
                )
                self.assertNotEqual(
                    result.status,
                    WriterAuthorizationStatus.ALLOW,
                )

    def test_revoked_denied(self):
        result = self.assess(
            status=replace(
                self.status,
                status=AuthorizationStatus.REVOKED,
            )
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_superseded_denied(self):
        result = self.assess(
            status=replace(
                self.status,
                status=AuthorizationStatus.SUPERSEDED,
            )
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_expired_denied(self):
        result = self.assess(
            status=replace(
                self.status,
                status=AuthorizationStatus.EXPIRED,
            )
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_identity_mismatch(self):
        result = self.assess(
            status=replace(
                self.status,
                authorization_id=str(uuid.uuid4()),
            )
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_authority_mismatch(self):
        result = self.assess(
            status=replace(
                self.status,
                authority_id="different-authority",
            )
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_revision_mismatch(self):
        result = self.assess(
            status=replace(self.status, revision=2)
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_disallowed_operation(self):
        evidence = replace(
            self.evidence,
            allowed_operations=("SELL",),
        )
        result = self.assess(evidence=evidence)
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_invalid_operation(self):
        result = self.assess(operation="TRANSFER")
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_invalid_evidence(self):
        result = self.assess(
            evidence=replace(self.evidence, revision=0)
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )

    def test_invalid_status_record(self):
        result = self.assess(
            status=replace(self.status, revision=0)
        )
        self.assertEqual(
            result.status,
            WriterAuthorizationStatus.DENY,
        )


if __name__ == "__main__":
    unittest.main()
