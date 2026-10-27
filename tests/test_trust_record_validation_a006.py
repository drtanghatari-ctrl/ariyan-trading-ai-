"""A006-WB02-P3C5 structural validation tests."""

import unittest
from dataclasses import replace

from ariyan_trading.trust_authority import TrustRecord
from ariyan_trading.trust_record_validation import (
    TRUST_RECORD_VERSION,
    validate_trust_record,
)
from ariyan_trading.writer_policy import VERSION as POLICY_VERSION


class TrustRecordValidationTests(unittest.TestCase):

    def record(self):
        return TrustRecord(
            ledger_id="123e4567-e89b-42d3-a456-426614174000",
            enrollment_sequence=2,
            enrollment_digest="a" * 64,
            writer_policy_version=POLICY_VERSION,
            authority_id="independent-test-authority",
            revision=1,
            record_version=TRUST_RECORD_VERSION,
        )

    def test_valid_record(self):
        self.assertTrue(validate_trust_record(self.record()))

    def test_wrong_object_type(self):
        self.assertFalse(validate_trust_record(None))

    def test_noncanonical_uuid(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), ledger_id="123E4567-E89B-42D3-A456-426614174000")
        ))

    def test_non_v4_uuid(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), ledger_id="123e4567-e89b-12d3-a456-426614174000")
        ))

    def test_negative_sequence(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), enrollment_sequence=-1)
        ))

    def test_boolean_sequence(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), enrollment_sequence=True)
        ))

    def test_short_digest(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), enrollment_digest="a" * 63)
        ))

    def test_uppercase_digest(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), enrollment_digest="A" * 64)
        ))

    def test_invalid_digest_character(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), enrollment_digest="g" * 64)
        ))

    def test_wrong_policy_version(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), writer_policy_version="unsupported")
        ))

    def test_empty_authority(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), authority_id="")
        ))

    def test_oversized_authority(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), authority_id="x" * 129)
        ))

    def test_authority_control_character(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), authority_id="authority\ninvalid")
        ))

    def test_authority_whitespace(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), authority_id=" authority ")
        ))

    def test_authority_invalid_unicode(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), authority_id="invalid" + chr(0xD800))
        ))

    def test_zero_revision(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), revision=0)
        ))

    def test_boolean_revision(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), revision=True)
        ))

    def test_wrong_record_version(self):
        self.assertFalse(validate_trust_record(
            replace(self.record(), record_version="unsupported")
        ))

    def test_zero_sequence_is_structurally_valid(self):
        self.assertTrue(validate_trust_record(
            replace(self.record(), enrollment_sequence=0)
        ))


if __name__ == "__main__":
    unittest.main()
