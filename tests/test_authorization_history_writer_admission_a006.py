"""A006 C2D-04B2C4B3 history-writer admission tests."""

import unittest

from ariyan_trading.authorization_history_writer_admission import (
    HistoryEnrollmentState,
    assess_history_writer_admission,
)
from ariyan_trading.authorization_status import AuthorizationStatus
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus as Decision,
)


class HistoryWriterAdmissionTests(unittest.TestCase):

    def assess(self, **kwargs):
        return assess_history_writer_admission(
            operation=kwargs.pop("operation", "APPEND_HISTORY"),
            **kwargs,
        )

    def test_missing_enrollment_uncertain(self):
        self.assertIs(self.assess().status, Decision.UNCERTAIN)

    def test_invalid_enrollment_denied(self):
        result = self.assess(
            enrollment_state=HistoryEnrollmentState.INVALID,
        )
        self.assertIs(result.status, Decision.DENY)

    def test_untrusted_enrollment_classification_denied(self):
        for value in ("authenticated", True, None, object()):
            with self.subTest(value=value):
                self.assertIs(
                    self.assess(enrollment_state=value).status,
                    Decision.DENY,
                )

    def test_unsupported_operations_denied(self):
        for operation in ("BUY", "SELL", "", None, True, 1):
            with self.subTest(operation=operation):
                self.assertIs(
                    self.assess(operation=operation).status,
                    Decision.DENY,
                )

    def test_terminal_authority_denied(self):
        for status in (
            AuthorizationStatus.REVOKED,
            AuthorizationStatus.SUPERSEDED,
            AuthorizationStatus.EXPIRED,
        ):
            with self.subTest(status=status):
                self.assertIs(
                    self.assess(
                        enrollment_state=HistoryEnrollmentState.AUTHENTICATED,
                        authority_status=status,
                    ).status,
                    Decision.DENY,
                )

    def test_untrusted_authority_status_denied(self):
        for value in ("active", None, True, object()):
            with self.subTest(value=value):
                self.assertIs(
                    self.assess(authority_status=value).status,
                    Decision.DENY,
                )

    def test_authenticated_enrollment_unknown_authority_uncertain(self):
        self.assertIs(
            self.assess(
                enrollment_state=HistoryEnrollmentState.AUTHENTICATED,
            ).status,
            Decision.UNCERTAIN,
        )

    def test_claimed_active_authority_never_allows(self):
        result = self.assess(
            enrollment_state=HistoryEnrollmentState.AUTHENTICATED,
            authority_status=AuthorizationStatus.ACTIVE,
        )
        self.assertIs(result.status, Decision.UNCERTAIN)

    def test_no_combination_allows(self):
        for enrollment in HistoryEnrollmentState:
            for authority in AuthorizationStatus:
                with self.subTest(
                    enrollment=enrollment,
                    authority=authority,
                ):
                    result = self.assess(
                        enrollment_state=enrollment,
                        authority_status=authority,
                    )
                    self.assertIsNot(result.status, Decision.ALLOW)


if __name__ == "__main__":
    unittest.main()
