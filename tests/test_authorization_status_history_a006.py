import json
import unittest
import uuid
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    VERSION as OBSERVATION_VERSION,
    AuthorizationStatusObservation,
)
from ariyan_trading.authorization_status_history import (
    VERSION,
    DOMAIN,
    AuthorizationStatusHistoryEntry,
    validate_status_history_entry,
    canonical_status_history_entry,
)


class AuthorizationStatusHistoryTests(unittest.TestCase):

    def setUp(self):
        self.record = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        self.observation = AuthorizationStatusObservation(
            version=OBSERVATION_VERSION,
            status_record=self.record,
            source_id="source-1",
            sequence=7,
            observed_at=100,
            valid_until=200,
        )

        self.entry = AuthorizationStatusHistoryEntry(
            version=VERSION,
            stream_id=str(uuid.uuid4()),
            history_sequence=1,
            observation=self.observation,
        )

    def test_valid_entry(self):
        self.assertTrue(validate_status_history_entry(self.entry))

    def test_wrong_object_rejected(self):
        self.assertFalse(validate_status_history_entry(None))

    def test_wrong_version_rejected(self):
        self.assertFalse(
            validate_status_history_entry(
                replace(self.entry, version="wrong")
            )
        )

    def test_invalid_stream_id_rejected(self):
        self.assertFalse(
            validate_status_history_entry(
                replace(self.entry, stream_id="not-a-uuid")
            )
        )

    def test_zero_sequence_rejected(self):
        self.assertFalse(
            validate_status_history_entry(
                replace(self.entry, history_sequence=0)
            )
        )

    def test_boolean_sequence_rejected(self):
        self.assertFalse(
            validate_status_history_entry(
                replace(self.entry, history_sequence=True)
            )
        )

    def test_invalid_observation_rejected(self):
        observation = replace(self.observation, sequence=-1)
        self.assertFalse(
            validate_status_history_entry(
                replace(self.entry, observation=observation)
            )
        )

    def test_entry_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.entry.history_sequence = 2

    def test_canonical_encoding_is_deterministic(self):
        first = canonical_status_history_entry(self.entry)
        second = canonical_status_history_entry(self.entry)
        self.assertEqual(first, second)

    def test_domain_separator(self):
        encoded = canonical_status_history_entry(self.entry)
        self.assertTrue(encoded.startswith(DOMAIN))

    def test_canonical_json_fields(self):
        encoded = canonical_status_history_entry(self.entry)
        payload = json.loads(encoded[len(DOMAIN):])

        self.assertEqual(
            payload["history_sequence"],
            self.entry.history_sequence,
        )
        self.assertEqual(
            payload["stream_id"],
            self.entry.stream_id,
        )
        self.assertEqual(
            payload["observation"]["sequence"],
            self.observation.sequence,
        )
        self.assertEqual(
            payload["observation"]["status_record"]["status"],
            "active",
        )

    def test_history_and_observation_sequences_are_distinct(self):
        encoded = canonical_status_history_entry(self.entry)
        payload = json.loads(encoded[len(DOMAIN):])

        self.assertEqual(payload["history_sequence"], 1)
        self.assertEqual(payload["observation"]["sequence"], 7)

    def test_status_change_changes_encoding(self):
        record = replace(
            self.record,
            status=AuthorizationStatus.REVOKED,
        )
        observation = replace(
            self.observation,
            status_record=record,
        )
        changed = replace(self.entry, observation=observation)

        self.assertNotEqual(
            canonical_status_history_entry(self.entry),
            canonical_status_history_entry(changed),
        )

    def test_sequence_change_changes_encoding(self):
        changed = replace(self.entry, history_sequence=2)

        self.assertNotEqual(
            canonical_status_history_entry(self.entry),
            canonical_status_history_entry(changed),
        )

    def test_invalid_entry_cannot_be_encoded(self):
        invalid = replace(self.entry, history_sequence=-1)

        with self.assertRaises(ValueError):
            canonical_status_history_entry(invalid)


if __name__ == "__main__":
    unittest.main()
