"""A006 B4-B3B2 provenance-contract tests."""

import unittest
from dataclasses import replace

from ariyan_trading.authorization_history_root_binding import (
    VERSION as BINDING_VERSION,
    ALGORITHM,
    HistoryRootBinding,
)
from ariyan_trading.authorization_history_root_provenance import (
    VERSION,
    HistoryRootProvenance,
    validate_history_root_provenance,
)
from ariyan_trading.authorization_status import AuthorizationStatus


class RootProvenanceTests(unittest.TestCase):

    def setUp(self):
        self.binding = HistoryRootBinding(
            version=BINDING_VERSION,
            root_authority_id="human-root-1",
            algorithm=ALGORITHM,
            public_key_sha256="a" * 64,
            enrollment_revision=2,
            trust_reference="external-pin-1",
        )
        self.record = HistoryRootProvenance(
            version=VERSION,
            binding=self.binding,
            lifecycle_revision=2,
            status=AuthorizationStatus.ACTIVE,
            provenance_reference="human-approval-record-1",
        )

    def test_valid_structure(self):
        self.assertTrue(
            validate_history_root_provenance(self.record)
        )

    def test_wrong_version(self):
        self.assertFalse(validate_history_root_provenance(
            replace(self.record, version="wrong")
        ))

    def test_invalid_binding(self):
        bad = replace(self.binding, public_key_sha256="bad")
        self.assertFalse(validate_history_root_provenance(
            replace(self.record, binding=bad)
        ))

    def test_revision_rollback(self):
        self.assertFalse(validate_history_root_provenance(
            replace(self.record, lifecycle_revision=1)
        ))

    def test_invalid_revision_types(self):
        for value in (None, True, 0, "2"):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_provenance(
                    replace(self.record, lifecycle_revision=value)
                ))

    def test_invalid_provenance_reference(self):
        for value in (None, "", " bad ", True):
            with self.subTest(value=value):
                self.assertFalse(validate_history_root_provenance(
                    replace(self.record, provenance_reference=value)
                ))

    def test_all_statuses_are_structurally_valid(self):
        for status in AuthorizationStatus:
            with self.subTest(status=status):
                self.assertTrue(validate_history_root_provenance(
                    replace(self.record, status=status)
                ))

    def test_invalid_status(self):
        self.assertFalse(validate_history_root_provenance(
            replace(self.record, status="active")
        ))

    def test_wrong_record_type(self):
        self.assertFalse(
            validate_history_root_provenance(None)
        )

    def test_no_trust_or_admission_claim(self):
        self.assertTrue(validate_history_root_provenance(self.record))
        self.assertFalse(hasattr(self.record, "authenticated"))
        self.assertFalse(hasattr(self.record, "authorized"))


if __name__ == "__main__":
    unittest.main()
