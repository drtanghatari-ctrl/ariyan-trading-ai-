"""A006 B4-B3A human-root enrollment contract tests."""

import unittest
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.authorization_history_root_binding import (
    VERSION as BINDING_VERSION,
    ALGORITHM,
    HistoryRootBinding,
)
from ariyan_trading.authorization_history_root_enrollment import (
    VERSION,
    HistoryRootEnrollment,
    validate_history_root_enrollment,
)
from ariyan_trading.authorization_status import AuthorizationStatus


class HistoryRootEnrollmentTests(unittest.TestCase):

    def setUp(self):
        binding = HistoryRootBinding(
            version=BINDING_VERSION,
            root_authority_id="human-root-1",
            algorithm=ALGORITHM,
            public_key_sha256="a" * 64,
            enrollment_revision=2,
            trust_reference="external-human-enrollment-1",
        )
        self.record = HistoryRootEnrollment(
            version=VERSION,
            binding=binding,
            status=AuthorizationStatus.ACTIVE,
            lifecycle_revision=2,
        )

    def test_valid_active_record(self):
        self.assertTrue(validate_history_root_enrollment(self.record))

    def test_all_defined_statuses_structurally_valid(self):
        for status in AuthorizationStatus:
            with self.subTest(status=status):
                self.assertTrue(validate_history_root_enrollment(
                    replace(self.record, status=status)
                ))

    def test_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.record.lifecycle_revision = 3

    def test_invalid_version(self):
        self.assertFalse(validate_history_root_enrollment(
            replace(self.record, version="other")
        ))

    def test_invalid_binding(self):
        invalid = replace(
            self.record.binding,
            public_key_sha256="INVALID",
        )
        self.assertFalse(validate_history_root_enrollment(
            replace(self.record, binding=invalid)
        ))

    def test_invalid_status(self):
        for value in ("active", None, True):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_enrollment(
                    replace(self.record, status=value)
                ))

    def test_invalid_lifecycle_revision(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_enrollment(
                    replace(self.record, lifecycle_revision=value)
                ))

    def test_lifecycle_cannot_precede_enrollment_revision(self):
        self.assertFalse(validate_history_root_enrollment(
            replace(self.record, lifecycle_revision=1)
        ))

    def test_wrong_type(self):
        self.assertFalse(validate_history_root_enrollment(None))
        self.assertFalse(validate_history_root_enrollment({}))

    def test_active_does_not_prove_trust(self):
        self.assertTrue(validate_history_root_enrollment(self.record))
        self.assertEqual(
            self.record.status,
            AuthorizationStatus.ACTIVE,
        )
        self.assertFalse(hasattr(self.record, "trusted"))
        self.assertFalse(hasattr(self.record, "authorized"))


if __name__ == "__main__":
    unittest.main()
