"""A006-WB02-P3C2 evidence classifier tests."""

import unittest

from ariyan_trading.enrollment_evidence import (
    DatabaseEvidence as DB,
    PolicyEvidence as Policy,
    TrustEvidence as Trust,
    classify_enrollment_evidence,
)
from ariyan_trading.enrollment_state import EnrollmentState


class EnrollmentEvidenceTests(unittest.TestCase):

    def classify(
        self,
        database,
        policy,
        trust,
        authoritative=True,
        uncertain=False,
    ):
        return classify_enrollment_evidence(
            database=database,
            policy=policy,
            trust=trust,
            trust_authoritative=authoritative,
            publication_uncertain=uncertain,
        )

    def test_authoritative_legacy(self):
        result = self.classify(
            DB.ABSENT, Policy.ABSENT, Trust.ABSENT
        )
        self.assertEqual(result.state, EnrollmentState.LEGACY)
        self.assertFalse(result.enrollment_verified)

    def test_legacy_without_authority_rejected(self):
        result = self.classify(
            DB.ABSENT, Policy.ABSENT, Trust.ABSENT,
            authoritative=False,
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_managed_consistent(self):
        result = self.classify(
            DB.MANAGED, Policy.VERIFIED, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.MANAGED)
        self.assertTrue(result.enrollment_verified)

    def test_preparing(self):
        result = self.classify(
            DB.PREPARING, Policy.ABSENT, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.PREPARING)

    def test_preparing_with_verified_policy_is_not_managed(self):
        result = self.classify(
            DB.PREPARING, Policy.VERIFIED, Trust.ENROLLED
        )
        self.assertEqual(
            result.state, EnrollmentState.PREPARING
        )
        self.assertFalse(result.enrollment_verified)

    def test_deleted_database_marker(self):
        result = self.classify(
            DB.ABSENT, Policy.VERIFIED, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_deleted_policy(self):
        result = self.classify(
            DB.MANAGED, Policy.ABSENT, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_unavailable_registry(self):
        result = self.classify(
            DB.ABSENT, Policy.ABSENT, Trust.UNAVAILABLE
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_unavailable_policy(self):
        result = self.classify(
            DB.MANAGED, Policy.UNAVAILABLE, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_conflicting_registry(self):
        result = self.classify(
            DB.MANAGED, Policy.VERIFIED, Trust.ABSENT
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_invalid_database(self):
        result = self.classify(
            DB.INVALID, Policy.VERIFIED, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_invalid_policy(self):
        result = self.classify(
            DB.MANAGED, Policy.INVALID, Trust.ENROLLED
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_invalid_trust(self):
        result = self.classify(
            DB.MANAGED, Policy.VERIFIED, Trust.INVALID
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_uncertain_publication(self):
        result = self.classify(
            DB.MANAGED, Policy.VERIFIED, Trust.ENROLLED,
            uncertain=True,
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_invalid_input(self):
        result = classify_enrollment_evidence(
            database="managed",
            policy=Policy.VERIFIED,
            trust=Trust.ENROLLED,
            trust_authoritative=True,
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_invalid_authority_flag(self):
        result = classify_enrollment_evidence(
            database=DB.MANAGED,
            policy=Policy.VERIFIED,
            trust=Trust.ENROLLED,
            trust_authoritative=1,
        )
        self.assertEqual(result.state, EnrollmentState.INVALID)


if __name__ == "__main__":
    unittest.main()
