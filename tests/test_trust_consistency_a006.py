"""A006-WB02-P3C7 trust consistency regression tests."""

import unittest
from dataclasses import replace

from ariyan_trading.trust_authority import TrustRecord
from ariyan_trading.trust_consistency import (
    trust_record_matches_policy,
)
from ariyan_trading.trust_record_validation import (
    TRUST_RECORD_VERSION,
)
from ariyan_trading.writer_policy import (
    VERSION as POLICY_VERSION,
)


class TrustConsistencyTests(unittest.TestCase):

    def record(self):
        return TrustRecord(
            ledger_id="123e4567-e89b-42d3-a456-426614174000",
            enrollment_sequence=2,
            enrollment_digest="a" * 64,
            writer_policy_version=POLICY_VERSION,
            authority_id="test-independent-authority",
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

    def test_matching_evidence(self):
        self.assertTrue(
            trust_record_matches_policy(self.record(), self.policy())
        )

    def test_different_ledger(self):
        record = replace(
            self.record(),
            ledger_id="123e4567-e89b-42d3-a456-426614174001",
        )
        self.assertFalse(
            trust_record_matches_policy(record, self.policy())
        )

    def test_different_sequence(self):
        record = replace(self.record(), enrollment_sequence=3)
        self.assertFalse(
            trust_record_matches_policy(record, self.policy())
        )

    def test_different_digest(self):
        record = replace(self.record(), enrollment_digest="b" * 64)
        self.assertFalse(
            trust_record_matches_policy(record, self.policy())
        )

    def test_invalid_record(self):
        record = replace(self.record(), revision=0)
        self.assertFalse(
            trust_record_matches_policy(record, self.policy())
        )

    def test_missing_policy_field(self):
        policy = self.policy()
        del policy["enrollment_digest"]
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_extra_policy_field(self):
        policy = self.policy()
        policy["unexpected"] = True
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_wrong_policy_type(self):
        self.assertFalse(
            trust_record_matches_policy(self.record(), None)
        )

    def test_wrong_policy_version(self):
        policy = self.policy()
        policy["version"] = "unsupported"
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_wrong_writer_mode(self):
        policy = self.policy()
        policy["writer_mode"] = "legacy"
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_boolean_sequence(self):
        policy = self.policy()
        policy["enrollment_sequence"] = True
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_malformed_policy_digest(self):
        policy = self.policy()
        policy["enrollment_digest"] = "invalid"
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )


    def test_policy_ledger_wrong_type(self):
        policy = self.policy()
        policy["ledger_id"] = 123
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_policy_digest_wrong_type(self):
        policy = self.policy()
        policy["enrollment_digest"] = None
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_policy_sequence_negative(self):
        policy = self.policy()
        policy["enrollment_sequence"] = -1
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_policy_ledger_noncanonical(self):
        policy = self.policy()
        policy["ledger_id"] = policy["ledger_id"].upper()
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )

    def test_policy_digest_uppercase(self):
        policy = self.policy()
        policy["enrollment_digest"] = "A" * 64
        self.assertFalse(
            trust_record_matches_policy(self.record(), policy)
        )


if __name__ == "__main__":
    unittest.main()
