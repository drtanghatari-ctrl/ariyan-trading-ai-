"""A006-WB02-P3C4 trust interface tests."""

import unittest
from dataclasses import replace

from ariyan_trading.trust_record_validation import (
    TRUST_RECORD_VERSION,
)
from ariyan_trading.trust_authority import (
    TrustLookup,
    TrustLookupStatus as Status,
    TrustRecord,
    classify_trust_lookup,
)


class TrustAuthorityTests(unittest.TestCase):

    def record(self):
        return TrustRecord(
            ledger_id="123e4567-e89b-42d3-a456-426614174000",
            enrollment_sequence=2,
            enrollment_digest="a" * 64,
            writer_policy_version="ARIYAN-A006-WRITER-POLICY-V1",
            authority_id="test-authority",
            revision=1,
            record_version=TRUST_RECORD_VERSION,
        )

    def test_authenticated_present(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=self.record(),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.PRESENT
        )

    def test_present_without_record(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_present_without_authentication(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=self.record(),
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_authoritative_absence(self):
        lookup = TrustLookup(
            status=Status.ABSENT,
            history_complete=True,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.ABSENT
        )

    def test_absence_without_history(self):
        lookup = TrustLookup(
            status=Status.ABSENT,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_absence_without_authentication(self):
        lookup = TrustLookup(
            status=Status.ABSENT,
            history_complete=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_absence_with_record(self):
        lookup = TrustLookup(
            status=Status.ABSENT,
            record=self.record(),
            history_complete=True,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_unavailable(self):
        lookup = TrustLookup(status=Status.UNAVAILABLE)
        self.assertEqual(
            classify_trust_lookup(lookup), Status.UNAVAILABLE
        )

    def test_unavailable_with_record(self):
        lookup = TrustLookup(
            status=Status.UNAVAILABLE,
            record=self.record(),
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_unavailable_cannot_claim_authentication(self):
        lookup = TrustLookup(
            status=Status.UNAVAILABLE,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_unavailable_cannot_claim_complete_history(self):
        lookup = TrustLookup(
            status=Status.UNAVAILABLE,
            history_complete=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_invalid(self):
        lookup = TrustLookup(status=Status.INVALID)
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_wrong_lookup_type(self):
        self.assertEqual(
            classify_trust_lookup("absent"), Status.INVALID
        )

    def test_invalid_boolean_type(self):
        lookup = TrustLookup(
            status=Status.ABSENT,
            history_complete=1,
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )


    def test_present_rejects_wrong_record_version(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=replace(
                self.record(),
                record_version="unsupported",
            ),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_present_rejects_malformed_digest(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=replace(
                self.record(),
                enrollment_digest="invalid",
            ),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_present_rejects_invalid_ledger_identity(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=replace(
                self.record(),
                ledger_id="not-a-uuid",
            ),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_present_rejects_negative_revision(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=replace(
                self.record(),
                revision=-1,
            ),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )

    def test_present_rejects_invalid_authority(self):
        lookup = TrustLookup(
            status=Status.PRESENT,
            record=replace(
                self.record(),
                authority_id="",
            ),
            authenticated=True,
        )
        self.assertEqual(
            classify_trust_lookup(lookup), Status.INVALID
        )


if __name__ == "__main__":
    unittest.main()
