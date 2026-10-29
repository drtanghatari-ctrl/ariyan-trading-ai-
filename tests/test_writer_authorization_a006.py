"""A006 P3C12-B3 writer authorization regression tests."""

import unittest

from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus,
    assess_writer_authorization,
)


class WriterAuthorizationTests(unittest.TestCase):

    def test_buy_cannot_be_authorized(self):
        result = assess_writer_authorization(operation="BUY")
        self.assertIs(
            result.status,
            WriterAuthorizationStatus.UNCERTAIN,
        )

    def test_sell_cannot_be_authorized(self):
        result = assess_writer_authorization(operation="SELL")
        self.assertIs(
            result.status,
            WriterAuthorizationStatus.UNCERTAIN,
        )

    def test_invalid_operation_is_denied(self):
        for operation in ("HOLD", "", None, 1, True):
            with self.subTest(operation=operation):
                result = assess_writer_authorization(
                    operation=operation,
                )
                self.assertIs(
                    result.status,
                    WriterAuthorizationStatus.DENY,
                )

    def test_caller_supplied_evidence_cannot_grant_permission(self):
        result = assess_writer_authorization(
            operation="BUY",
            enrollment_decision=object(),
            trust_lookup=object(),
        )
        self.assertIs(
            result.status,
            WriterAuthorizationStatus.UNCERTAIN,
        )

    def test_no_operation_returns_allow(self):
        for operation in ("BUY", "SELL", "HOLD", None):
            with self.subTest(operation=operation):
                result = assess_writer_authorization(
                    operation=operation,
                )
                self.assertIsNot(
                    result.status,
                    WriterAuthorizationStatus.ALLOW,
                )


if __name__ == "__main__":
    unittest.main()
