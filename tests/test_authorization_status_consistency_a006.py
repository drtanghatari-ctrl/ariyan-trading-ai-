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
from ariyan_trading.authorization_status_consistency import (
    assess_status_consistency,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus as Status,
)


class AuthorizationStatusConsistencyTests(unittest.TestCase):

    def setUp(self):
        record = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        self.previous = AuthorizationStatusObservation(
            version=VERSION,
            status_record=record,
            source_id="source-1",
            sequence=10,
            observed_at=100,
            valid_until=200,
        )

        self.candidate = replace(
            self.previous,
            sequence=11,
            observed_at=110,
            valid_until=210,
        )

    def assess(self, previous=None, candidate=None):
        return assess_status_consistency(
            previous=self.previous if previous is None else previous,
            candidate=self.candidate if candidate is None else candidate,
        )

    def test_consistent_observations_remain_uncertain(self):
        self.assertEqual(self.assess().status, Status.UNCERTAIN)

    def test_identical_observation_remains_uncertain(self):
        self.assertEqual(
            self.assess(candidate=self.previous).status,
            Status.UNCERTAIN,
        )

    def test_invalid_previous_denied(self):
        self.assertEqual(
            assess_status_consistency(
                previous=None,
                candidate=self.candidate,
            ).status,
            Status.DENY,
        )

    def test_invalid_candidate_denied(self):
        self.assertEqual(
            assess_status_consistency(
                previous=self.previous,
                candidate=None,
            ).status,
            Status.DENY,
        )

    def test_authorization_identity_change_denied(self):
        record = replace(
            self.candidate.status_record,
            authorization_id=str(uuid.uuid4()),
        )
        candidate = replace(self.candidate, status_record=record)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_authority_change_denied(self):
        record = replace(
            self.candidate.status_record,
            authority_id="authority-2",
        )
        candidate = replace(self.candidate, status_record=record)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_source_change_denied(self):
        candidate = replace(
            self.candidate,
            source_id="source-2",
        )
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_sequence_regression_denied(self):
        candidate = replace(self.candidate, sequence=9)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_equal_sequence_conflict_denied(self):
        candidate = replace(
            self.candidate,
            sequence=10,
        )
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_revision_regression_denied(self):
        old_record = replace(
            self.previous.status_record,
            revision=2,
        )
        previous = replace(
            self.previous,
            status_record=old_record,
        )
        self.assertEqual(
            self.assess(previous=previous).status,
            Status.DENY,
        )

    def test_timestamp_regression_denied(self):
        candidate = replace(
            self.candidate,
            observed_at=99,
        )
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_revoked_cannot_be_reactivated(self):
        record = replace(
            self.previous.status_record,
            status=AuthorizationStatus.REVOKED,
        )
        previous = replace(self.previous, status_record=record)
        self.assertEqual(
            self.assess(previous=previous).status,
            Status.DENY,
        )

    def test_superseded_cannot_be_reactivated(self):
        record = replace(
            self.previous.status_record,
            status=AuthorizationStatus.SUPERSEDED,
        )
        previous = replace(self.previous, status_record=record)
        self.assertEqual(
            self.assess(previous=previous).status,
            Status.DENY,
        )

    def test_expired_cannot_be_reactivated(self):
        record = replace(
            self.previous.status_record,
            status=AuthorizationStatus.EXPIRED,
        )
        previous = replace(self.previous, status_record=record)
        self.assertEqual(
            self.assess(previous=previous).status,
            Status.DENY,
        )

    def test_candidate_revoked_denied(self):
        record = replace(
            self.candidate.status_record,
            status=AuthorizationStatus.REVOKED,
        )
        candidate = replace(self.candidate, status_record=record)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_candidate_superseded_denied(self):
        record = replace(
            self.candidate.status_record,
            status=AuthorizationStatus.SUPERSEDED,
        )
        candidate = replace(self.candidate, status_record=record)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_candidate_expired_denied(self):
        record = replace(
            self.candidate.status_record,
            status=AuthorizationStatus.EXPIRED,
        )
        candidate = replace(self.candidate, status_record=record)
        self.assertEqual(
            self.assess(candidate=candidate).status,
            Status.DENY,
        )

    def test_no_positive_authorization(self):
        for status in AuthorizationStatus:
            record = replace(
                self.candidate.status_record,
                status=status,
            )
            candidate = replace(
                self.candidate,
                status_record=record,
            )
            self.assertNotEqual(
                self.assess(candidate=candidate).status,
                Status.ALLOW,
            )


if __name__ == "__main__":
    unittest.main()
