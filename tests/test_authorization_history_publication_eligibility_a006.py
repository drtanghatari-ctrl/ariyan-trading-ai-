"""A006 C2D-04B2C3A publication eligibility tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_anchor_io import (
    write_history_anchor,
)
from ariyan_trading.authorization_history_publication_eligibility import (
    verify_history_publication_eligibility,
)
from ariyan_trading.authorization_history_prepare_coordinator import (
    prepare_history_publication,
)
from ariyan_trading.authorization_history_publication_control import (
    initialize_publication_control,
)
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
from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
    verify_history_store,
)


class PublicationEligibilityTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        self.anchor_path = (
            Path(self.temp.name) / "history-anchor.json"
        )

        self.db = sqlite3.connect(
            ":memory:", isolation_level=None
        )
        self.addCleanup(self.db.close)

        self.db.execute("PRAGMA synchronous=FULL")

        self.stream_id = str(uuid4())
        self.key = b"E" * 32

        self.db.execute("BEGIN IMMEDIATE")
        initialize_history_store(self.db, self.stream_id)
        initialize_publication_control(self.db)
        self.db.commit()

        self.db.execute("BEGIN")
        sequence, digest = verify_history_store(
            self.db, self.stream_id
        )
        self.db.rollback()

        self.predecessor = create_history_anchor(
            self.stream_id, sequence, digest, self.key
        )

        write_history_anchor(
            self.anchor_path,
            self.predecessor,
            self.key,
        )

    def entry(self, sequence=1):
        status = AuthorizationStatusRecord(
            authorization_id=str(uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        observation = AuthorizationStatusObservation(
            version=OBS_VERSION,
            status_record=status,
            source_id="source-1",
            sequence=sequence,
            observed_at=100 + sequence,
            valid_until=200 + sequence,
        )

        return AuthorizationStatusHistoryEntry(
            version=HISTORY_VERSION,
            stream_id=self.stream_id,
            history_sequence=sequence,
            observation=observation,
        )

    def prepare(self):
        return prepare_history_publication(
            self.db,
            self.stream_id,
            self.entry(),
            self.predecessor,
            self.key,
        )

    def eligible(self, predecessor=None, path=None):
        self.db.execute("BEGIN")
        try:
            return verify_history_publication_eligibility(
                self.db,
                self.stream_id,
                self.predecessor
                if predecessor is None else predecessor,
                self.anchor_path if path is None else path,
                self.key,
            )
        finally:
            self.db.rollback()

    def test_first_publication_eligible(self):
        prepared = self.prepare()
        result = self.eligible()

        self.assertEqual(
            result["state"], "ELIGIBLE_FOR_PUBLICATION"
        )
        self.assertEqual(result["previous_sequence"], 0)
        self.assertEqual(result["sequence"], 1)
        self.assertEqual(result["digest"], prepared["digest"])

    def test_requires_transaction(self):
        self.prepare()

        with self.assertRaises(ValueError):
            verify_history_publication_eligibility(
                self.db,
                self.stream_id,
                self.predecessor,
                self.anchor_path,
                self.key,
            )

    def test_wrong_predecessor_sequence_rejected(self):
        self.prepare()

        wrong = create_history_anchor(
            self.stream_id,
            2,
            self.predecessor["history_digest"],
            self.key,
        )

        with self.assertRaises(ValueError):
            self.eligible(predecessor=wrong)

    def test_wrong_predecessor_digest_rejected(self):
        self.prepare()

        wrong = create_history_anchor(
            self.stream_id,
            0,
            "0" * 64,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.eligible(predecessor=wrong)

    def test_wrong_predecessor_stream_rejected(self):
        self.prepare()

        wrong = create_history_anchor(
            str(uuid4()),
            0,
            self.predecessor["history_digest"],
            self.key,
        )

        with self.assertRaises(ValueError):
            self.eligible(predecessor=wrong)

    def test_missing_anchor_rejected(self):
        self.prepare()

        self.anchor_path.unlink()

        with self.assertRaises(FileNotFoundError):
            self.eligible()

    def test_tampered_disk_anchor_rejected(self):
        self.prepare()

        self.anchor_path.write_bytes(b"invalid anchor")

        with self.assertRaises(ValueError):
            self.eligible()

    def test_disk_anchor_mismatch_rejected(self):
        self.prepare()

        different = create_history_anchor(
            self.stream_id,
            2,
            self.predecessor["history_digest"],
            self.key,
        )

        write_history_anchor(
            self.anchor_path,
            different,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.eligible()

    def test_eligibility_does_not_mutate_evidence(self):
        self.prepare()

        original_anchor = self.anchor_path.read_bytes()

        self.db.execute("BEGIN")
        before = self.db.total_changes

        result = verify_history_publication_eligibility(
            self.db,
            self.stream_id,
            self.predecessor,
            self.anchor_path,
            self.key,
        )

        after = self.db.total_changes
        self.db.rollback()

        self.assertEqual(
            result["state"], "ELIGIBLE_FOR_PUBLICATION"
        )
        self.assertEqual(before, after)
        self.assertEqual(
            self.anchor_path.read_bytes(),
            original_anchor,
        )


    def test_second_history_publication_eligible(self):
        from ariyan_trading.authorization_history_publication_intent import (
            create_publication_intent,
        )
        from ariyan_trading.authorization_history_publication_store import (
            record_publication_intent,
        )
        from ariyan_trading.authorization_status_history_store import (
            append_history_entry,
        )

        first = self.prepare()

        # Simulate the already-verified completed publication
        # of sequence 1. This is fixture setup, not a production
        # recovery or publication coordinator.
        self.db.execute("BEGIN IMMEDIATE")

        self.db.execute(
            "DELETE FROM auth_pubctl_state "
            "WHERE key='publication_intent'"
        )
        self.db.execute(
            "UPDATE auth_pubctl_state SET value='READY' "
            "WHERE key='publication_state'"
        )

        self.db.commit()

        self.predecessor = create_history_anchor(
            self.stream_id,
            first["sequence"],
            first["digest"],
            self.key,
        )

        write_history_anchor(
            self.anchor_path,
            self.predecessor,
            self.key,
        )

        self.db.execute("BEGIN IMMEDIATE")

        try:
            sequence, digest = append_history_entry(
                self.db,
                self.stream_id,
                self.entry(sequence=2),
            )

            intent = create_publication_intent(
                self.stream_id,
                sequence,
                digest,
            )

            record_publication_intent(
                self.db,
                intent,
            )

            self.db.commit()

        except BaseException:
            if self.db.in_transaction:
                self.db.rollback()
            raise

        result = self.eligible()

        self.assertEqual(result["previous_sequence"], 1)
        self.assertEqual(result["sequence"], 2)
        self.assertEqual(result["digest"], digest)

    def test_corrupted_history_commitment_rejected(self):
        self.prepare()

        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "UPDATE authorization_history_commitments "
            "SET digest=? WHERE history_sequence=1",
            ("0" * 64,),
        )
        self.db.commit()

        with self.assertRaises(ValueError):
            self.eligible()

    def test_unexpected_publication_metadata_rejected(self):
        self.prepare()

        self.db.execute("BEGIN IMMEDIATE")
        self.db.execute(
            "INSERT INTO auth_pubctl_state(key,value) "
            "VALUES (?,?)",
            ("unexpected_key", "unexpected_value"),
        )
        self.db.commit()

        with self.assertRaises(ValueError):
            self.eligible()


if __name__ == "__main__":
    unittest.main()
