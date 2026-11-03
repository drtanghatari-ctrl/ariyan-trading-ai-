"""A006 C2D-04B2C4B4-A authority evidence contract tests."""

import unittest
import uuid
from dataclasses import FrozenInstanceError, replace

from ariyan_trading.authorization_history_writer_authority import (
    VERSION,
    APPEND_HISTORY,
    HistoryWriterAuthorityEvidence,
    validate_history_writer_authority_evidence as valid,
)


class HistoryWriterAuthorityTests(unittest.TestCase):

    def setUp(self):
        self.record = HistoryWriterAuthorityEvidence(
            version=VERSION,
            authorization_id=str(uuid.uuid4()),
            root_authority_id="human-root-1",
            writer_id="history-writer-1",
            stream_id=str(uuid.uuid4()),
            revision=1,
            allowed_operations=(APPEND_HISTORY,),
            valid_from=100,
            valid_until=200,
            status_reference="root-status-1",
        )

    def test_valid_evidence(self):
        self.assertTrue(valid(self.record))

    def test_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.record.writer_id = "other-writer"

    def test_wrong_type(self):
        self.assertFalse(valid(object()))

    def test_wrong_version(self):
        self.assertFalse(
            valid(replace(self.record, version="unknown"))
        )

    def test_invalid_identifiers(self):
        for field in ("authorization_id", "stream_id"):
            with self.subTest(field=field):
                self.assertFalse(
                    valid(replace(self.record, **{field: "invalid"}))
                )

    def test_invalid_names(self):
        for field in (
            "root_authority_id",
            "writer_id",
            "status_reference",
        ):
            with self.subTest(field=field):
                self.assertFalse(
                    valid(replace(self.record, **{field: ""}))
                )

    def test_invalid_revision(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                self.assertFalse(
                    valid(replace(self.record, revision=value))
                )

    def test_invalid_operations(self):
        for value in (
            (),
            ("BUY",),
            ("SELL",),
            ("APPEND_HISTORY", "APPEND_HISTORY"),
            ["APPEND_HISTORY"],
            (True,),
        ):
            with self.subTest(value=value):
                self.assertFalse(
                    valid(replace(self.record, allowed_operations=value))
                )

    def test_invalid_time_interval(self):
        for start, end in (
            (100, 100),
            (200, 100),
            (-1, 200),
            (True, 200),
            (100, False),
        ):
            with self.subTest(start=start, end=end):
                self.assertFalse(
                    valid(replace(
                        self.record,
                        valid_from=start,
                        valid_until=end,
                    ))
                )

    def test_structural_validation_is_not_authorization(self):
        self.assertTrue(valid(self.record))
        self.assertFalse(hasattr(self.record, "authorized"))
        self.assertFalse(hasattr(self.record, "private_key"))


if __name__ == "__main__":
    unittest.main()
