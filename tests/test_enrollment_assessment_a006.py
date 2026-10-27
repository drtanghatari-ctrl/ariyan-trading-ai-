"""A006-WB02-P3C8 conservative assessment tests."""

import unittest
from dataclasses import replace

from ariyan_trading.enrollment_assessment import assess_enrollment
from ariyan_trading.enrollment_evidence import (
    DatabaseEvidence as DB,
    PolicyEvidence as Policy,
)
from ariyan_trading.enrollment_state import EnrollmentState
from ariyan_trading.trust_authority import (
    TrustLookup,
    TrustLookupStatus as Status,
    TrustRecord,
)
from ariyan_trading.trust_record_validation import (
    TRUST_RECORD_VERSION,
)
from ariyan_trading.writer_policy import VERSION as POLICY_VERSION


class EnrollmentAssessmentTests(unittest.TestCase):

    def record(self):
        return TrustRecord(
            ledger_id="123e4567-e89b-42d3-a456-426614174000",
            enrollment_sequence=2,
            enrollment_digest="a" * 64,
            writer_policy_version=POLICY_VERSION,
            authority_id="test-authority",
            revision=1,
            record_version=TRUST_RECORD_VERSION,
        )

    def policy(self):
        record = self.record()
        return {
            "version": POLICY_VERSION,
            "ledger_id": record.ledger_id,
            "writer_mode": "managed-v1",
            "enrollment_sequence": record.enrollment_sequence,
            "enrollment_digest": record.enrollment_digest,
        }

    def present(self, record=None):
        return TrustLookup(
            status=Status.PRESENT,
            record=self.record() if record is None else record,
            authenticated=True,
        )

    def assess(self, **changes):
        arguments = {
            "database": DB.MANAGED,
            "policy": Policy.VERIFIED,
            "lookup": self.present(),
            "verified_policy": self.policy(),
        }
        arguments.update(changes)
        return assess_enrollment(**arguments)

    def test_matching_records_not_authoritative(self):
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)
        self.assertFalse(result.enrollment_verified)

    def test_matching_records_cannot_authorize_managed(self):
        self.assertNotEqual(
            self.assess().state, EnrollmentState.MANAGED
        )

    def test_absence_cannot_establish_legacy(self):
        result = self.assess(
            database=DB.ABSENT,
            policy=Policy.ABSENT,
            lookup=TrustLookup(
                status=Status.ABSENT,
                history_complete=True,
                authenticated=True,
            ),
            verified_policy=None,
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_mismatched_ledger_invalid(self):
        record = replace(
            self.record(),
            ledger_id="123e4567-e89b-42d3-a456-426614174001",
        )
        self.assertEqual(
            self.assess(lookup=self.present(record)).state,
            EnrollmentState.INVALID,
        )

    def test_mismatched_digest_invalid(self):
        record = replace(
            self.record(),
            enrollment_digest="b" * 64,
        )
        self.assertEqual(
            self.assess(lookup=self.present(record)).state,
            EnrollmentState.INVALID,
        )

    def test_mismatched_sequence_invalid(self):
        record = replace(
            self.record(),
            enrollment_sequence=3,
        )
        self.assertEqual(
            self.assess(lookup=self.present(record)).state,
            EnrollmentState.INVALID,
        )

    def test_malformed_trust_invalid(self):
        self.assertEqual(
            self.assess(
                lookup=TrustLookup(
                    status=Status.PRESENT,
                    authenticated=True,
                )
            ).state,
            EnrollmentState.INVALID,
        )

    def test_unavailable_remains_uncertain(self):
        self.assertEqual(
            self.assess(
                lookup=TrustLookup(status=Status.UNAVAILABLE)
            ).state,
            EnrollmentState.UNCERTAIN,
        )

    def test_missing_verified_policy_invalid(self):
        self.assertEqual(
            self.assess(verified_policy=None).state,
            EnrollmentState.INVALID,
        )

    def test_publication_uncertain(self):
        self.assertEqual(
            self.assess(publication_uncertain=True).state,
            EnrollmentState.UNCERTAIN,
        )

    def test_invalid_database(self):
        self.assertEqual(
            self.assess(database="managed").state,
            EnrollmentState.INVALID,
        )

    def test_invalid_boolean(self):
        self.assertEqual(
            self.assess(publication_uncertain=1).state,
            EnrollmentState.INVALID,
        )


if __name__ == "__main__":
    unittest.main()
