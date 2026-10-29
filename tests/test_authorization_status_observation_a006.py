import unittest
import uuid

from dataclasses import replace

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    VERSION,
    AuthorizationStatusObservation,
    validate_authorization_status_observation,
)


class AuthorizationStatusObservationTests(unittest.TestCase):

    def setUp(self):
        self.record = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        self.observation = AuthorizationStatusObservation(
            version=VERSION,
            status_record=self.record,
            source_id="status-source-1",
            sequence=1,
            observed_at=100,
            valid_until=200,
        )

    def valid(self, observation):
        return validate_authorization_status_observation(
            observation
        )

    def test_valid_structure(self):
        self.assertTrue(self.valid(self.observation))

    def test_wrong_version(self):
        self.assertFalse(
            self.valid(replace(self.observation, version="wrong"))
        )

    def test_invalid_status_record(self):
        record = replace(self.record, revision=0)
        self.assertFalse(
            self.valid(
                replace(self.observation, status_record=record)
            )
        )

    def test_invalid_source(self):
        self.assertFalse(
            self.valid(
                replace(self.observation, source_id=" source ")
            )
        )

    def test_negative_sequence(self):
        self.assertFalse(
            self.valid(replace(self.observation, sequence=-1))
        )

    def test_boolean_sequence(self):
        self.assertFalse(
            self.valid(replace(self.observation, sequence=True))
        )

    def test_negative_observed_at(self):
        self.assertFalse(
            self.valid(replace(self.observation, observed_at=-1))
        )

    def test_boolean_observed_at(self):
        self.assertFalse(
            self.valid(replace(self.observation, observed_at=True))
        )

    def test_equal_expiry(self):
        self.assertFalse(
            self.valid(replace(self.observation, valid_until=100))
        )

    def test_expiry_before_observation(self):
        self.assertFalse(
            self.valid(replace(self.observation, valid_until=99))
        )

    def test_boolean_expiry(self):
        self.assertFalse(
            self.valid(replace(self.observation, valid_until=True))
        )

    def test_wrong_object_type(self):
        self.assertFalse(self.valid(None))

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            self.observation.sequence = 2

    def test_revoked_status_is_structurally_valid(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.REVOKED,
        )
        self.assertTrue(
            self.valid(
                replace(self.observation, status_record=record)
            )
        )


if __name__ == "__main__":
    unittest.main()
