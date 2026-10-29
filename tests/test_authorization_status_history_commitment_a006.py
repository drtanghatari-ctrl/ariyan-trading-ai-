import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    VERSION as OBS_VERSION,
    AuthorizationStatusObservation,
)
from ariyan_trading.authorization_status_history import (
    VERSION as HISTORY_VERSION,
    AuthorizationStatusHistoryEntry,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
    entry_history_commitment,
    verify_history_chain,
)


class AuthorizationStatusHistoryCommitmentTests(unittest.TestCase):

    def setUp(self):
        self.stream_id = str(uuid.uuid4())

        self.record = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        self.observation = AuthorizationStatusObservation(
            version=OBS_VERSION,
            status_record=self.record,
            source_id="source-1",
            sequence=10,
            observed_at=100,
            valid_until=200,
        )

        self.first = AuthorizationStatusHistoryEntry(
            version=HISTORY_VERSION,
            stream_id=self.stream_id,
            history_sequence=1,
            observation=self.observation,
        )

        self.second = replace(
            self.first,
            history_sequence=2,
            observation=replace(
                self.observation,
                sequence=11,
                observed_at=110,
                valid_until=210,
            ),
        )

    def chain_digest(self, entries):
        digest = opening_history_commitment(self.stream_id)

        for entry in entries:
            digest = entry_history_commitment(digest, entry)

        return digest

    def test_opening_commitment_is_deterministic(self):
        self.assertEqual(
            opening_history_commitment(self.stream_id),
            opening_history_commitment(self.stream_id),
        )

    def test_opening_commitment_binds_stream(self):
        self.assertNotEqual(
            opening_history_commitment(self.stream_id),
            opening_history_commitment(str(uuid.uuid4())),
        )

    def test_invalid_stream_rejected(self):
        with self.assertRaises(ValueError):
            opening_history_commitment("invalid")

    def test_entry_commitment_is_deterministic(self):
        opening = opening_history_commitment(self.stream_id)

        self.assertEqual(
            entry_history_commitment(opening, self.first),
            entry_history_commitment(opening, self.first),
        )

    def test_entry_changes_digest(self):
        opening = opening_history_commitment(self.stream_id)

        changed = replace(
            self.first,
            observation=replace(
                self.observation,
                sequence=99,
            ),
        )

        self.assertNotEqual(
            entry_history_commitment(opening, self.first),
            entry_history_commitment(opening, changed),
        )

    def test_previous_digest_changes_commitment(self):
        first = opening_history_commitment(self.stream_id)
        second = entry_history_commitment(first, self.first)

        self.assertNotEqual(
            entry_history_commitment(first, self.second),
            entry_history_commitment(second, self.second),
        )

    def test_invalid_previous_digest_rejected(self):
        with self.assertRaises(ValueError):
            entry_history_commitment("invalid", self.first)

    def test_uppercase_digest_rejected(self):
        with self.assertRaises(ValueError):
            entry_history_commitment("A" * 64, self.first)

    def test_invalid_entry_rejected(self):
        opening = opening_history_commitment(self.stream_id)

        with self.assertRaises(ValueError):
            entry_history_commitment(opening, None)

    def test_valid_empty_chain(self):
        opening = opening_history_commitment(self.stream_id)

        self.assertEqual(
            verify_history_chain(self.stream_id, [], opening),
            opening,
        )

    def test_valid_two_entry_chain(self):
        entries = [self.first, self.second]
        expected = self.chain_digest(entries)

        self.assertEqual(
            verify_history_chain(
                self.stream_id,
                entries,
                expected,
            ),
            expected,
        )

    def test_missing_entry_rejected(self):
        expected = self.chain_digest([self.first, self.second])

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first],
                expected,
            )

    def test_reordered_entries_rejected(self):
        expected = self.chain_digest([self.first, self.second])

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.second, self.first],
                expected,
            )

    def test_duplicate_sequence_rejected(self):
        duplicate = replace(
            self.second,
            history_sequence=1,
        )

        expected = self.chain_digest([self.first, duplicate])

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first, duplicate],
                expected,
            )

    def test_sequence_gap_rejected(self):
        skipped = replace(
            self.second,
            history_sequence=3,
        )

        expected = self.chain_digest([self.first, skipped])

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first, skipped],
                expected,
            )

    def test_stream_substitution_rejected(self):
        substituted = replace(
            self.second,
            stream_id=str(uuid.uuid4()),
        )

        expected = self.chain_digest([self.first, substituted])

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first, substituted],
                expected,
            )

    def test_status_tampering_rejected(self):
        expected = self.chain_digest([self.first, self.second])

        changed_record = replace(
            self.second.observation.status_record,
            status=AuthorizationStatus.REVOKED,
        )

        changed_observation = replace(
            self.second.observation,
            status_record=changed_record,
        )

        tampered = replace(
            self.second,
            observation=changed_observation,
        )

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first, tampered],
                expected,
            )

    def test_wrong_expected_digest_rejected(self):
        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [self.first],
                "0" * 64,
            )

    def test_noncanonical_expected_digest_rejected(self):
        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                [],
                "A" * 64,
            )

    def test_invalid_entries_container_rejected(self):
        opening = opening_history_commitment(self.stream_id)

        with self.assertRaises(ValueError):
            verify_history_chain(
                self.stream_id,
                None,
                opening,
            )


if __name__ == "__main__":
    unittest.main()
