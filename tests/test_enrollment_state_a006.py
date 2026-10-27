"""A006-WB02-P3C pure enrollment state regression tests."""

import unittest

from ariyan_trading.enrollment_state import (
    EnrollmentState,
    EnrollmentEvent,
    classify_enrollment_state,
    transition_enrollment,
)


class EnrollmentStateTests(unittest.TestCase):

    def test_legacy_classification(self):
        result = classify_enrollment_state(
            EnrollmentState.LEGACY
        )
        self.assertTrue(result.direct_writes_allowed)
        self.assertFalse(result.enrollment_complete)

    def test_preparing_blocks_direct_writes(self):
        result = classify_enrollment_state(
            EnrollmentState.PREPARING
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_managed_blocks_direct_writes(self):
        result = classify_enrollment_state(
            EnrollmentState.MANAGED
        )
        self.assertFalse(result.direct_writes_allowed)
        self.assertTrue(result.enrollment_complete)

    def test_uncertain_blocks_direct_writes(self):
        result = classify_enrollment_state(
            EnrollmentState.UNCERTAIN
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_invalid_blocks_direct_writes(self):
        result = classify_enrollment_state(
            EnrollmentState.INVALID
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_preparation_transition(self):
        result = transition_enrollment(
            EnrollmentState.LEGACY,
            EnrollmentEvent.PREPARATION_COMMITTED,
        )
        self.assertEqual(
            result.state, EnrollmentState.PREPARING
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_verified_publication_transition(self):
        result = transition_enrollment(
            EnrollmentState.PREPARING,
            EnrollmentEvent.PUBLICATION_VERIFIED,
        )
        self.assertEqual(
            result.state, EnrollmentState.MANAGED
        )
        self.assertTrue(result.enrollment_complete)

    def test_uncertain_preparation_fails_closed(self):
        result = transition_enrollment(
            EnrollmentState.PREPARING,
            EnrollmentEvent.OUTCOME_UNCERTAIN,
        )
        self.assertEqual(
            result.state, EnrollmentState.UNCERTAIN
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_invalid_evidence_fails_closed(self):
        result = transition_enrollment(
            EnrollmentState.PREPARING,
            EnrollmentEvent.EVIDENCE_INVALID,
        )
        self.assertEqual(
            result.state, EnrollmentState.INVALID
        )
        self.assertFalse(result.direct_writes_allowed)

    def test_cannot_skip_preparation(self):
        with self.assertRaises(ValueError):
            transition_enrollment(
                EnrollmentState.LEGACY,
                EnrollmentEvent.PUBLICATION_VERIFIED,
            )

    def test_cannot_downgrade_managed(self):
        with self.assertRaises(ValueError):
            transition_enrollment(
                EnrollmentState.MANAGED,
                EnrollmentEvent.PREPARATION_COMMITTED,
            )

    def test_uncertain_cannot_auto_recover(self):
        with self.assertRaises(ValueError):
            transition_enrollment(
                EnrollmentState.UNCERTAIN,
                EnrollmentEvent.PUBLICATION_VERIFIED,
            )

    def test_invalid_cannot_auto_recover(self):
        with self.assertRaises(ValueError):
            transition_enrollment(
                EnrollmentState.INVALID,
                EnrollmentEvent.PUBLICATION_VERIFIED,
            )

    def test_invalid_state_type_rejected(self):
        with self.assertRaises(TypeError):
            classify_enrollment_state("legacy")

    def test_invalid_event_type_rejected(self):
        with self.assertRaises(TypeError):
            transition_enrollment(
                EnrollmentState.LEGACY,
                "preparation_committed",
            )


if __name__ == "__main__":
    unittest.main()
