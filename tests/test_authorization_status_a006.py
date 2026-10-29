import unittest
import uuid
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
    validate_authorization_status,
)


class AuthorizationStatusTests(unittest.TestCase):

    def setUp(self):
        self.record = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="primary-authority",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

    def test_valid_record(self):
        self.assertTrue(
            validate_authorization_status(self.record)
        )

    def test_all_statuses_structurally_valid(self):
        for status in AuthorizationStatus:
            with self.subTest(status=status):
                record = replace(self.record, status=status)
                self.assertTrue(
                    validate_authorization_status(record)
                )

    def test_invalid_revision(self):
        for revision in (0, -1, True, 1.5, "1"):
            with self.subTest(revision=revision):
                record = replace(self.record, revision=revision)
                self.assertFalse(
                    validate_authorization_status(record)
                )

    def test_invalid_status(self):
        for status in ("active", None, True, 1):
            with self.subTest(status=status):
                record = replace(self.record, status=status)
                self.assertFalse(
                    validate_authorization_status(record)
                )

    def test_invalid_authorization_id(self):
        record = replace(
            self.record,
            authorization_id="invalid",
        )
        self.assertFalse(
            validate_authorization_status(record)
        )

    def test_invalid_authority_id(self):
        record = replace(
            self.record,
            authority_id="",
        )
        self.assertFalse(
            validate_authorization_status(record)
        )

    def test_wrong_object(self):
        self.assertFalse(
            validate_authorization_status(None)
        )

    def test_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.record.revision = 2


if __name__ == "__main__":
    unittest.main()
