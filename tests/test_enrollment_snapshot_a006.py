"""A006-WB02-P3C10 owned read-snapshot tests."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.enrollment_snapshot import assess_enrollment_snapshot
from ariyan_trading.enrollment_state import EnrollmentState
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor
from ariyan_trading.trust_authority import (
    TrustLookup,
    TrustLookupStatus,
    TrustRecord,
)
from ariyan_trading.trust_record_validation import TRUST_RECORD_VERSION
from ariyan_trading.writer_policy import (
    VERSION as POLICY_VERSION,
    create_writer_policy,
)


KEY = b"A006-P3C10-disposable-test-key-1234567890"


class EnrollmentSnapshotTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        root = Path(self.temp.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "checkpoint.json"

        self.ledger = DurableLedger(
            self.database,
            opening_cash="1000.00",
        )
        self.addCleanup(self.ledger.close)

        db = self.ledger.db
        db.execute("BEGIN")
        try:
            digest = verify_protected_journal(
                db, self.ledger.opening_cash
            )
            sequence = db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
        finally:
            db.rollback()

        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, KEY),
            KEY,
        )

        self.policy = create_writer_policy(
            self.ledger.ledger_identity,
            sequence,
            digest,
            KEY,
        )

        self.lookup = TrustLookup(
            status=TrustLookupStatus.PRESENT,
            record=TrustRecord(
                ledger_id=self.ledger.ledger_identity,
                enrollment_sequence=sequence,
                enrollment_digest=digest,
                writer_policy_version=POLICY_VERSION,
                authority_id="test-authority",
                revision=1,
                record_version=TRUST_RECORD_VERSION,
            ),
            authenticated=True,
        )

    def assess(self, **options):
        return assess_enrollment_snapshot(
            self.database,
            self.ledger.opening_cash,
            self.anchor,
            KEY,
            self.policy,
            KEY,
            self.lookup,
            **options,
        )

    def test_valid_local_evidence_remains_uncertain(self):
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)
        self.assertFalse(result.enrollment_verified)

    def test_stale_checkpoint_invalid(self):
        self.ledger.record_buy("later-buy", "1", "10")
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_missing_checkpoint_invalid(self):
        self.anchor.unlink()
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_missing_database_rejected_without_creation(self):
        missing = self.database.parent / "missing.sqlite"
        with self.assertRaises(ValueError):
            assess_enrollment_snapshot(
                missing,
                self.ledger.opening_cash,
                self.anchor,
                KEY,
                self.policy,
                KEY,
                self.lookup,
            )
        self.assertFalse(missing.exists())

    def test_database_remains_writable_after_assessment(self):
        self.assess()
        self.ledger.record_buy("after-assessment", "1", "10")
        self.assertEqual(
            self.ledger.db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0],
            1,
        )

    def test_invalid_publication_flag_fails_closed(self):
        result = self.assess(publication_uncertain=1)
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_connection_closed_after_unexpected_exception(self):
        captured = []

        def fail_verification(db, *args, **kwargs):
            captured.append(db)
            raise RuntimeError("Injected verification failure")

        with patch(
            "ariyan_trading.enrollment_snapshot."
            "assess_verified_enrollment",
            side_effect=fail_verification,
        ):
            with self.assertRaisesRegex(
                RuntimeError, "Injected verification failure"
            ):
                self.assess()

        self.assertEqual(len(captured), 1)

        with self.assertRaises(sqlite3.ProgrammingError):
            captured[0].execute("SELECT 1")

    def test_read_only_uri_prevents_writes(self):
        uri = self.database.resolve().as_uri() + "?mode=ro"
        db = sqlite3.connect(
            uri, uri=True, isolation_level=None
        )
        try:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute(
                    "INSERT INTO ledger_meta(key,value) "
                    "VALUES ('P3C10_write_probe','blocked')"
                )
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
