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
)
from ariyan_trading.authorization_freshness import (
    assess_authorization_freshness,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus as Status,
)


class AuthorizationFreshnessTests(unittest.TestCase):

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

    def assess(self, observation=None, evaluation_time=150):
        return assess_authorization_freshness(
            observation=(
                self.observation
                if observation is None
                else observation
            ),
            evaluation_time=evaluation_time,
        )

    def test_active_remains_uncertain(self):
        self.assertEqual(self.assess().status, Status.UNCERTAIN)

    def test_start_boundary_uncertain(self):
        self.assertEqual(
            self.assess(evaluation_time=100).status,
            Status.UNCERTAIN,
        )

    def test_before_start_denied(self):
        self.assertEqual(
            self.assess(evaluation_time=99).status,
            Status.DENY,
        )

    def test_expiry_boundary_denied(self):
        self.assertEqual(
            self.assess(evaluation_time=200).status,
            Status.DENY,
        )

    def test_after_expiry_denied(self):
        self.assertEqual(
            self.assess(evaluation_time=201).status,
            Status.DENY,
        )

    def test_invalid_time_denied(self):
        self.assertEqual(
            self.assess(evaluation_time=-1).status,
            Status.DENY,
        )

    def test_boolean_time_denied(self):
        self.assertEqual(
            self.assess(evaluation_time=True).status,
            Status.DENY,
        )

    def test_invalid_observation_denied(self):
        observation = replace(
            self.observation,
            sequence=-1,
        )
        self.assertEqual(
            self.assess(observation=observation).status,
            Status.DENY,
        )

    def test_revoked_denied(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.REVOKED,
        )
        observation = replace(
            self.observation,
            status_record=record,
        )
        self.assertEqual(
            self.assess(observation=observation).status,
            Status.DENY,
        )

    def test_superseded_denied(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.SUPERSEDED,
        )
        observation = replace(
            self.observation,
            status_record=record,
        )
        self.assertEqual(
            self.assess(observation=observation).status,
            Status.DENY,
        )

    def test_expired_denied(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.EXPIRED,
        )
        observation = replace(
            self.observation,
            status_record=record,
        )
        self.assertEqual(
            self.assess(observation=observation).status,
            Status.DENY,
        )

    def test_unknown_remains_uncertain(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.UNKNOWN,
        )
        observation = replace(
            self.observation,
            status_record=record,
        )
        self.assertEqual(
            self.assess(observation=observation).status,
            Status.UNCERTAIN,
        )

    def test_no_positive_authorization(self):
        for status in AuthorizationStatus:
            record = replace(self.record, status=status)
            observation = replace(
                self.observation,
                status_record=record,
            )
            self.assertNotEqual(
                self.assess(observation=observation).status,
                Status.ALLOW,
            )


if __name__ == "__main__":
    unittest.main()
