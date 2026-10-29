import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AUTHORIZATION_EVIDENCE_VERSION,
    AuthorizationEvidence,
)
from ariyan_trading.authorization_request import (
    AuthorizationRequest,
    assess_request_binding,
    validate_authorization_request,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus as Status,
)


class AuthorizationRequestTests(unittest.TestCase):

    def setUp(self):
        ledger = str(uuid.uuid4())

        self.evidence = AuthorizationEvidence(
            version=AUTHORIZATION_EVIDENCE_VERSION,
            authorization_id=str(uuid.uuid4()),
            ledger_id=ledger,
            writer_id="writer-1",
            authority_id="authority-1",
            revision=1,
            allowed_operations=("BUY",),
            valid_from=100,
            valid_until=200,
        )

        self.request = AuthorizationRequest(
            ledger_id=ledger,
            writer_id="writer-1",
            operation="BUY",
            request_time=150,
        )

    def assess(self, evidence=None, request=None):
        return assess_request_binding(
            evidence=self.evidence if evidence is None else evidence,
            request=self.request if request is None else request,
        )

    def test_valid_request_structure(self):
        self.assertTrue(
            validate_authorization_request(self.request)
        )

    def test_matching_request_never_allows(self):
        self.assertEqual(
            self.assess().status,
            Status.UNCERTAIN,
        )

    def test_ledger_mismatch_denied(self):
        request = replace(
            self.request,
            ledger_id=str(uuid.uuid4()),
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.DENY,
        )

    def test_writer_mismatch_denied(self):
        request = replace(
            self.request,
            writer_id="writer-2",
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.DENY,
        )

    def test_operation_mismatch_denied(self):
        request = replace(
            self.request,
            operation="SELL",
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.DENY,
        )

    def test_before_validity_denied(self):
        request = replace(
            self.request,
            request_time=99,
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.DENY,
        )

    def test_at_expiry_denied(self):
        request = replace(
            self.request,
            request_time=200,
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.DENY,
        )

    def test_at_start_remains_uncertain(self):
        request = replace(
            self.request,
            request_time=100,
        )
        self.assertEqual(
            self.assess(request=request).status,
            Status.UNCERTAIN,
        )

    def test_invalid_time_denied(self):
        for value in (-1, True, 1.5, "150"):
            with self.subTest(value=value):
                request = replace(
                    self.request,
                    request_time=value,
                )
                self.assertEqual(
                    self.assess(request=request).status,
                    Status.DENY,
                )

    def test_invalid_evidence_denied(self):
        evidence = replace(
            self.evidence,
            revision=0,
        )
        self.assertEqual(
            self.assess(evidence=evidence).status,
            Status.DENY,
        )

    def test_wrong_request_type_denied(self):
        result = assess_request_binding(
            evidence=self.evidence,
            request=None,
        )
        self.assertEqual(result.status, Status.DENY)


if __name__ == "__main__":
    unittest.main()
