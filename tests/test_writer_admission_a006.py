"""A006 P3C12-B1: writer-admission tests."""

import unittest

from ariyan_trading.enrollment_state import (
    EnrollmentDecision,
    EnrollmentState,
    classify_enrollment_state,
)
from ariyan_trading.writer_admission import (
    legacy_direct_write_eligible,
)


class WriterAdmissionTests(unittest.TestCase):

    def test_legacy(self):
        decision = classify_enrollment_state(
            EnrollmentState.LEGACY
        )
        self.assertTrue(
            legacy_direct_write_eligible(decision)
        )

    def test_nonlegacy(self):
        for state in EnrollmentState:
            if state is EnrollmentState.LEGACY:
                continue

            with self.subTest(state=state):
                decision = classify_enrollment_state(state)
                self.assertFalse(
                    legacy_direct_write_eligible(decision)
                )

    def test_invalid_inputs(self):
        for value in (None, True, "legacy", {}, object()):
            with self.subTest(value=repr(value)):
                self.assertFalse(
                    legacy_direct_write_eligible(value)
                )

    def test_inconsistent_legacy(self):
        decision = EnrollmentDecision(
            EnrollmentState.LEGACY,
            False,
            False,
        )
        self.assertFalse(
            legacy_direct_write_eligible(decision)
        )

    def test_forged_managed_permission(self):
        decision = EnrollmentDecision(
            EnrollmentState.MANAGED,
            True,
            True,
        )
        self.assertFalse(
            legacy_direct_write_eligible(decision)
        )

    def test_invalid_flag_type(self):
        decision = EnrollmentDecision(
            EnrollmentState.LEGACY,
            1,
            False,
        )
        self.assertFalse(
            legacy_direct_write_eligible(decision)
        )

    def test_invalid_state_type(self):
        decision = EnrollmentDecision(
            "legacy",
            True,
            False,
        )
        self.assertFalse(
            legacy_direct_write_eligible(decision)
        )


if __name__ == "__main__":
    unittest.main()
