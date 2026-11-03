"""A006 B4-B2B immutable root binding tests."""

import unittest
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.authorization_history_root_binding import (
    VERSION,
    ALGORITHM,
    HistoryRootBinding,
    validate_history_root_binding,
)


class HistoryRootBindingTests(unittest.TestCase):

    def setUp(self):
        self.record = HistoryRootBinding(
            version=VERSION,
            root_authority_id="human-root-1",
            algorithm=ALGORITHM,
            public_key_sha256="a" * 64,
            enrollment_revision=1,
            trust_reference="external-human-enrollment-1",
        )

    def test_valid_record(self):
        self.assertTrue(validate_history_root_binding(self.record))

    def test_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.record.enrollment_revision = 2

    def test_invalid_version(self):
        self.assertFalse(validate_history_root_binding(
            replace(self.record, version="other")
        ))

    def test_invalid_root_identity(self):
        for value in ("", " root ", "\nroot", 42):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_binding(
                    replace(self.record, root_authority_id=value)
                ))

    def test_invalid_algorithm(self):
        for value in ("RSA", "ed25519", "", None):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_binding(
                    replace(self.record, algorithm=value)
                ))

    def test_invalid_fingerprint(self):
        for value in ("A" * 64, "z" * 64, "a" * 63, None):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_binding(
                    replace(self.record, public_key_sha256=value)
                ))

    def test_invalid_revision(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_binding(
                    replace(self.record, enrollment_revision=value)
                ))

    def test_invalid_trust_reference(self):
        for value in ("", " reference ", "\x00", None):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_binding(
                    replace(self.record, trust_reference=value)
                ))

    def test_wrong_record_type(self):
        self.assertFalse(validate_history_root_binding(None))
        self.assertFalse(validate_history_root_binding({}))

    def test_structure_does_not_grant_authority(self):
        self.assertTrue(validate_history_root_binding(self.record))
        self.assertFalse(hasattr(self.record, "trusted"))
        self.assertFalse(hasattr(self.record, "authorized"))


if __name__ == "__main__":
    unittest.main()
