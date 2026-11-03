"""A006 B4-B3C2 root-evidence evaluator tests."""

import unittest
from dataclasses import replace

from ariyan_trading.authorization_history_root_binding import (
    VERSION as BINDING_VERSION,
    ALGORITHM,
    HistoryRootBinding,
)
from ariyan_trading.authorization_history_root_enrollment import (
    VERSION as ENROLLMENT_VERSION,
    HistoryRootEnrollment,
)
from ariyan_trading.authorization_history_root_provenance import (
    VERSION as PROVENANCE_VERSION,
    HistoryRootProvenance,
)
from ariyan_trading.authorization_history_root_trust_result import (
    RootTrustComparison as C,
    validate_root_trust_result,
)
from ariyan_trading.authorization_history_root_evaluator import (
    evaluate_history_root_evidence,
)
from ariyan_trading.authorization_status import AuthorizationStatus


class RootEvidenceEvaluatorTests(unittest.TestCase):

    def setUp(self):
        binding = HistoryRootBinding(
            version=BINDING_VERSION,
            root_authority_id="human-root-1",
            algorithm=ALGORITHM,
            public_key_sha256="a" * 64,
            enrollment_revision=2,
            trust_reference="external-pin-1",
        )
        self.enrollment = HistoryRootEnrollment(
            version=ENROLLMENT_VERSION,
            binding=binding,
            status=AuthorizationStatus.ACTIVE,
            lifecycle_revision=3,
        )
        self.provenance = HistoryRootProvenance(
            version=PROVENANCE_VERSION,
            binding=binding,
            lifecycle_revision=3,
            status=AuthorizationStatus.ACTIVE,
            provenance_reference="approval-record-1",
        )

    def evaluate(self, enrollment=None, provenance=None,
                 identity="human-root-1", fingerprint="a" * 64):
        return evaluate_history_root_evidence(
            self.enrollment if enrollment is None else enrollment,
            self.provenance if provenance is None else provenance,
            identity,
            fingerprint,
        )

    def test_matching_evidence(self):
        result = self.evaluate()
        self.assertEqual(result.comparison, C.MATCH)
        self.assertFalse(result.independently_authenticated)
        self.assertTrue(validate_root_trust_result(result))

    def test_wrong_identity(self):
        self.assertEqual(
            self.evaluate(identity="different-root").comparison,
            C.MISMATCH,
        )

    def test_wrong_fingerprint(self):
        self.assertEqual(
            self.evaluate(fingerprint="b" * 64).comparison,
            C.MISMATCH,
        )

    def test_missing_external_anchor(self):
        for identity, fingerprint in (
            (None, "a" * 64),
            ("human-root-1", None),
        ):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.evaluate(
                        identity=identity,
                        fingerprint=fingerprint,
                    ).comparison,
                    C.UNAVAILABLE,
                )

    def test_invalid_external_anchor(self):
        for identity, fingerprint in (
            ("", "a" * 64),
            ("human-root-1", "bad"),
            (True, "a" * 64),
        ):
            with self.subTest(identity=identity):
                self.assertEqual(
                    self.evaluate(
                        identity=identity,
                        fingerprint=fingerprint,
                    ).comparison,
                    C.INVALID,
                )

    def test_binding_mismatch(self):
        altered = replace(
            self.provenance.binding,
            trust_reference="other-reference",
        )
        provenance = replace(self.provenance, binding=altered)
        self.assertEqual(
            self.evaluate(provenance=provenance).comparison,
            C.MISMATCH,
        )

    def test_lifecycle_revision_mismatch(self):
        provenance = replace(
            self.provenance,
            lifecycle_revision=4,
        )
        self.assertEqual(
            self.evaluate(provenance=provenance).comparison,
            C.MISMATCH,
        )

    def test_nonactive_enrollment(self):
        for status in AuthorizationStatus:
            if status is AuthorizationStatus.ACTIVE:
                continue
            with self.subTest(status=status):
                enrollment = replace(
                    self.enrollment, status=status,
                )
                self.assertEqual(
                    self.evaluate(enrollment=enrollment).comparison,
                    C.INVALID,
                )

    def test_nonactive_provenance(self):
        for status in AuthorizationStatus:
            if status is AuthorizationStatus.ACTIVE:
                continue
            with self.subTest(status=status):
                provenance = replace(
                    self.provenance, status=status,
                )
                self.assertEqual(
                    self.evaluate(provenance=provenance).comparison,
                    C.INVALID,
                )

    def test_invalid_enrollment(self):
        enrollment = replace(self.enrollment, lifecycle_revision=0)
        self.assertEqual(
            self.evaluate(enrollment=enrollment).comparison,
            C.INVALID,
        )

    def test_invalid_provenance(self):
        provenance = replace(
            self.provenance, provenance_reference="",
        )
        self.assertEqual(
            self.evaluate(provenance=provenance).comparison,
            C.INVALID,
        )

    def test_no_authorization_for_any_result(self):
        for result in (
            self.evaluate(),
            self.evaluate(identity="wrong"),
            self.evaluate(identity=None),
            self.evaluate(identity=""),
        ):
            self.assertFalse(result.independently_authenticated)
            self.assertFalse(hasattr(result, "authorized"))
            self.assertTrue(validate_root_trust_result(result))


if __name__ == "__main__":
    unittest.main()
