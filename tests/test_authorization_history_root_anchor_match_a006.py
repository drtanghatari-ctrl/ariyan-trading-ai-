"""A006 B4-B3B1 root-anchor matching tests."""

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
from ariyan_trading.authorization_history_root_anchor_match import (
    matches_external_root_anchor,
)
from ariyan_trading.authorization_status import AuthorizationStatus


class RootAnchorMatchTests(unittest.TestCase):

    def setUp(self):
        self.root_id = "human-root-1"
        self.fingerprint = "a" * 64

        binding = HistoryRootBinding(
            version=BINDING_VERSION,
            root_authority_id=self.root_id,
            algorithm=ALGORITHM,
            public_key_sha256=self.fingerprint,
            enrollment_revision=1,
            trust_reference="external-root-pin-1",
        )

        self.enrollment = HistoryRootEnrollment(
            version=ENROLLMENT_VERSION,
            binding=binding,
            status=AuthorizationStatus.ACTIVE,
            lifecycle_revision=1,
        )

    _UNSET = object()

    def match(
        self,
        enrollment=_UNSET,
        root_id=_UNSET,
        fingerprint=_UNSET,
    ):
        return matches_external_root_anchor(
            self.enrollment if enrollment is self._UNSET else enrollment,
            self.root_id if root_id is self._UNSET else root_id,
            self.fingerprint if fingerprint is self._UNSET else fingerprint,
        )

    def test_exact_match(self):
        self.assertTrue(self.match())

    def test_wrong_root_identity(self):
        self.assertFalse(self.match(root_id="different-root"))

    def test_wrong_fingerprint(self):
        self.assertFalse(self.match(fingerprint="b" * 64))

    def test_invalid_enrollment(self):
        invalid = replace(self.enrollment, lifecycle_revision=0)
        with self.assertRaises(ValueError):
            self.match(enrollment=invalid)

    def test_invalid_external_identity(self):
        for value in (None, "", " bad ", True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.match(root_id=value)

    def test_invalid_external_fingerprint(self):
        for value in (None, "", "A" * 64, "z" * 64, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.match(fingerprint=value)

    def test_active_status_does_not_change_match(self):
        for status in AuthorizationStatus:
            with self.subTest(status=status):
                record = replace(self.enrollment, status=status)
                self.assertTrue(self.match(enrollment=record))

    def test_match_does_not_grant_authority(self):
        self.assertTrue(self.match())
        self.assertFalse(hasattr(self.enrollment, "trusted"))
        self.assertFalse(hasattr(self.enrollment, "authorized"))


if __name__ == "__main__":
    unittest.main()
