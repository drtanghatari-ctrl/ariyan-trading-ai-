"""A006 B4-B3C1 root-trust comparison contract tests."""

import unittest
from dataclasses import replace

from ariyan_trading.authorization_history_root_trust_result import (
    RootTrustComparison,
    RootTrustResult,
    validate_root_trust_result,
)


class RootTrustResultTests(unittest.TestCase):

    def test_all_comparison_states(self):
        for comparison in RootTrustComparison:
            with self.subTest(comparison=comparison):
                self.assertTrue(validate_root_trust_result(
                    RootTrustResult(comparison)
                ))

    def test_match_not_authenticated(self):
        record = RootTrustResult(RootTrustComparison.MATCH)
        self.assertFalse(record.independently_authenticated)

    def test_authenticated_claim_rejected(self):
        record = RootTrustResult(
            RootTrustComparison.MATCH,
            independently_authenticated=True,
        )
        self.assertFalse(validate_root_trust_result(record))

    def test_authenticated_claim_rejected_for_every_state(self):
        for comparison in RootTrustComparison:
            with self.subTest(comparison=comparison):
                self.assertFalse(validate_root_trust_result(
                    RootTrustResult(comparison, True)
                ))

    def test_invalid_comparison(self):
        record = RootTrustResult("match")
        self.assertFalse(validate_root_trust_result(record))

    def test_invalid_authentication_type(self):
        for value in (None, 0, 1, "false"):
            with self.subTest(value=value):
                self.assertFalse(validate_root_trust_result(
                    RootTrustResult(RootTrustComparison.MATCH, value)
                ))

    def test_wrong_record_type(self):
        self.assertFalse(validate_root_trust_result(None))

    def test_immutable(self):
        record = RootTrustResult(RootTrustComparison.MATCH)
        with self.assertRaises(AttributeError):
            record.comparison = RootTrustComparison.MISMATCH

    def test_no_authorization_field(self):
        record = RootTrustResult(RootTrustComparison.MATCH)
        self.assertFalse(hasattr(record, "authorized"))
        self.assertFalse(hasattr(record, "writer_admitted"))


if __name__ == "__main__":
    unittest.main()
