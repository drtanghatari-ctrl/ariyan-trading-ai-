"""A006 C2D-04B2C4B2 authenticated enrollment tests."""

import sqlite3
import unittest
import uuid

from ariyan_trading.authorization_history_anchor import (
    create_history_anchor,
)
from ariyan_trading.authorization_history_writer_policy import (
    create_history_writer_policy,
)
from ariyan_trading.authorization_history_writer_enrollment_store import (
    initialize_enrollment_store,
)
from ariyan_trading.authorization_history_writer_enrollment_verifier import (
    verify_authenticated_writer_enrollment,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
)
from ariyan_trading.authorization_status_history_store import (
    initialize_history_store,
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
    append_history_entry,
)

class AuthenticatedEnrollmentTests(unittest.TestCase):

    def setUp(self):
        self.db = sqlite3.connect(
            ":memory:", isolation_level=None
        )

        self.stream_id = str(uuid.uuid4())
        self.key = b"K" * 32
        self.digest = opening_history_commitment(
            self.stream_id
        )

        self.policy = create_history_writer_policy(
            self.stream_id,
            0,
            self.digest,
            self.key,
        )

        self.anchor = create_history_anchor(
            self.stream_id,
            0,
            self.digest,
            self.key,
        )

        self.db.execute("BEGIN IMMEDIATE")

        initialize_history_store(
            self.db, self.stream_id
        )

        initialize_enrollment_store(
            self.db, self.policy
        )

        self.db.commit()

    def tearDown(self):
        if self.db.in_transaction:
            self.db.rollback()
        self.db.close()

    def verify(self, anchor=None, key=None, stream_id=None):
        self.db.execute("BEGIN")

        try:
            return verify_authenticated_writer_enrollment(
                self.db,
                self.stream_id if stream_id is None else stream_id,
                self.anchor if anchor is None else anchor,
                self.key if key is None else key,
            )
        finally:
            self.db.rollback()

    def test_valid_enrollment(self):
        result = self.verify()

        self.assertEqual(
            result["state"],
            "AUTHENTICATED_ENROLLMENT",
        )
        self.assertEqual(
            result["enrollment_sequence"], 0
        )
        self.assertEqual(
            result["enrollment_digest"], self.digest
        )

    def test_requires_transaction(self):
        with self.assertRaises(ValueError):
            verify_authenticated_writer_enrollment(
                self.db,
                self.stream_id,
                self.anchor,
                self.key,
            )

    def test_wrong_key_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(key=b"X" * 32)

    def test_wrong_stream_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(stream_id=str(uuid.uuid4()))

    def test_modified_policy_mac_rejected(self):
        self.db.execute(
            "UPDATE auth_writer_enrollment_state "
            "SET value=json_set(value, '$.mac', ?)",
            ("0" * 64,),
        )

        with self.assertRaises(ValueError):
            self.verify()

    def test_modified_anchor_rejected(self):
        other_anchor = create_history_anchor(
            self.stream_id,
            0,
            "1" * 64,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.verify(anchor=other_anchor)

    def test_future_enrollment_checkpoint_rejected(self):
        self.db.execute(
            "BEGIN IMMEDIATE"
        )

        self.db.execute(
            "DROP TABLE auth_writer_enrollment_state"
        )

        future_policy = create_history_writer_policy(
            self.stream_id,
            1,
            "1" * 64,
            self.key,
        )

        initialize_enrollment_store(
            self.db,
            future_policy,
        )

        self.db.commit()

        future_anchor = create_history_anchor(
            self.stream_id,
            1,
            "1" * 64,
            self.key,
        )

        with self.assertRaises(ValueError):
            self.verify(anchor=future_anchor)

    def test_missing_enrollment_table_rejected(self):
        self.db.execute(
            "DROP TABLE auth_writer_enrollment_state"
        )

        with self.assertRaises(ValueError):
            self.verify()

    def test_verification_does_not_mutate_history(self):
        first = self.verify()
        second = self.verify()

        self.assertEqual(first, second)
        self.assertFalse(self.db.in_transaction)


    def make_entry(self, sequence):
        status = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
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

    def append_valid_entry(self, sequence):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            result = append_history_entry(
                self.db,
                self.stream_id,
                self.make_entry(sequence),
            )
            self.db.commit()
            return result
        except BaseException:
            self.db.rollback()
            raise

    def enroll_at_sequence_one(self):
        sequence, digest = self.append_valid_entry(1)

        policy = create_history_writer_policy(
            self.stream_id,
            sequence,
            digest,
            self.key,
        )

        anchor = create_history_anchor(
            self.stream_id,
            sequence,
            digest,
            self.key,
        )

        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "DROP TABLE auth_writer_enrollment_state"
            )
            initialize_enrollment_store(
                self.db,
                policy,
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

        return anchor, digest

    def test_nonzero_enrollment_checkpoint(self):
        anchor, digest = self.enroll_at_sequence_one()

        result = self.verify(anchor=anchor)

        self.assertEqual(result["enrollment_sequence"], 1)
        self.assertEqual(result["enrollment_digest"], digest)
        self.assertEqual(result["current_sequence"], 1)

    def test_enrollment_survives_history_growth(self):
        anchor, digest = self.enroll_at_sequence_one()

        self.append_valid_entry(2)

        result = self.verify(anchor=anchor)

        self.assertEqual(result["enrollment_sequence"], 1)
        self.assertEqual(result["enrollment_digest"], digest)
        self.assertEqual(result["current_sequence"], 2)

    def test_wrong_historical_digest_rejected(self):
        anchor, digest = self.enroll_at_sequence_one()

        incorrect_digest = (
            "0" * 64 if digest != "0" * 64 else "1" * 64
        )

        incorrect_policy = create_history_writer_policy(
            self.stream_id,
            1,
            incorrect_digest,
            self.key,
        )

        incorrect_anchor = create_history_anchor(
            self.stream_id,
            1,
            incorrect_digest,
            self.key,
        )

        self.db.execute("BEGIN IMMEDIATE")
        try:
            self.db.execute(
                "UPDATE auth_writer_enrollment_state "
                "SET value=? WHERE key='policy'",
                (
                    __import__("json").dumps(
                        incorrect_policy,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    ),
                ),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

        with self.assertRaisesRegex(
            ValueError,
            "Enrollment history commitment mismatch",
        ):
            self.verify(anchor=incorrect_anchor)

    def test_canonical_policy_mac_tampering_rejected(self):
        import json

        modified = dict(self.policy)

        modified["mac"] = (
            "0" * 64
            if self.policy["mac"] != "0" * 64
            else "1" * 64
        )

        canonical = json.dumps(
            modified,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

        self.db.execute(
            "UPDATE auth_writer_enrollment_state "
            "SET value=? WHERE key='policy'",
            (canonical,),
        )

        with self.assertRaisesRegex(
            ValueError,
            "authentication failed",
        ):
            self.verify()


if __name__ == "__main__":
    unittest.main()
