"""A006-WB02-P3C9 verified enrollment assessment tests."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.enrollment_state import EnrollmentState
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor
from ariyan_trading.trust_authority import (
    TrustLookup,
    TrustLookupStatus,
    TrustRecord,
)
from ariyan_trading.trust_record_validation import TRUST_RECORD_VERSION
from ariyan_trading.verified_enrollment_assessment import (
    assess_verified_enrollment,
)
from ariyan_trading.writer_policy import (
    VERSION as POLICY_VERSION,
    create_writer_policy,
)


KEY = b"A006-P3C9-disposable-test-key-1234567890"


class VerifiedEnrollmentAssessmentTests(unittest.TestCase):

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

        root = Path(self.temp.name)
        self.anchor = root / "checkpoint.json"

        self.ledger = DurableLedger(
            root / "ledger.sqlite",
            opening_cash="1000.00",
        )
        self.addCleanup(self.ledger.close)

        self.sequence, self.digest = self.checkpoint()

        self.policy = create_writer_policy(
            self.ledger.ledger_identity,
            self.sequence,
            self.digest,
            KEY,
        )

    def checkpoint(self):
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            digest = verify_protected_journal(
                db, self.ledger.opening_cash
            )
            sequence = db.execute(
                "SELECT COUNT(*) FROM ledger_entries"
            ).fetchone()[0]
            db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise

        write_anchor(
            self.anchor,
            create_anchor(sequence, digest, KEY),
            KEY,
        )
        return sequence, digest

    def record(self):
        return TrustRecord(
            ledger_id=self.ledger.ledger_identity,
            enrollment_sequence=self.sequence,
            enrollment_digest=self.digest,
            writer_policy_version=POLICY_VERSION,
            authority_id="test-authority",
            revision=1,
            record_version=TRUST_RECORD_VERSION,
        )

    def lookup(self, record=None):
        return TrustLookup(
            status=TrustLookupStatus.PRESENT,
            record=self.record() if record is None else record,
            authenticated=True,
        )

    def assess(self, *, policy=None, lookup=None, **options):
        db = self.ledger.db
        db.execute("BEGIN")
        try:
            return assess_verified_enrollment(
                db,
                self.ledger.opening_cash,
                self.anchor,
                KEY,
                self.policy if policy is None else policy,
                KEY,
                self.lookup() if lookup is None else lookup,
                **options,
            )
        finally:
            db.rollback()

    def test_verified_local_evidence_not_authoritative(self):
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)
        self.assertFalse(result.enrollment_verified)

    def test_wrong_trust_digest_invalid(self):
        record = replace(
            self.record(),
            enrollment_digest="b" * 64,
        )
        result = self.assess(lookup=self.lookup(record))
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_wrong_trust_sequence_invalid(self):
        record = replace(
            self.record(),
            enrollment_sequence=self.sequence + 1,
        )
        result = self.assess(lookup=self.lookup(record))
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_tampered_policy_invalid(self):
        policy = dict(self.policy)
        policy["enrollment_digest"] = "b" * 64
        result = self.assess(policy=policy)
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_missing_checkpoint_invalid(self):
        self.anchor.unlink()
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_checkpoint_path_is_directory_invalid(self):
        self.anchor.unlink()
        self.anchor.mkdir()
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_stale_checkpoint_invalid(self):
        self.ledger.record_buy("buy-after-anchor", "1", "10")
        result = self.assess()
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_unavailable_trust_uncertain(self):
        result = self.assess(
            lookup=TrustLookup(
                status=TrustLookupStatus.UNAVAILABLE
            )
        )
        self.assertEqual(result.state, EnrollmentState.UNCERTAIN)

    def test_invalid_publication_flag(self):
        result = self.assess(publication_uncertain=1)
        self.assertEqual(result.state, EnrollmentState.INVALID)

    def test_transaction_required(self):
        with self.assertRaisesRegex(
            ValueError, "Active transaction"
        ):
            assess_verified_enrollment(
                self.ledger.db,
                self.ledger.opening_cash,
                self.anchor,
                KEY,
                self.policy,
                KEY,
                self.lookup(),
            )


if __name__ == "__main__":
    unittest.main()
