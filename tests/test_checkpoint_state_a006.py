"""A006 pure checkpoint state classifier regression tests."""

import unittest

from app.ariyan_trading.checkpoint_state import (
    CheckpointState,
    classify_checkpoint,
)

DIGEST = "ab" * 32
OTHER = "cd" * 32


class CheckpointStateA006Tests(unittest.TestCase):

    def classify(self, **overrides):
        values = dict(
            journal_sequence=2,
            journal_digest=DIGEST,
            anchor_sequence=2,
            anchor_digest=DIGEST,
            anchor_authenticated=True,
        )
        values.update(overrides)
        return classify_checkpoint(**values)

    def test_truthy_authentication_flag_rejected(self):
        result = self.classify(anchor_authenticated="yes")
        self.assertEqual(result.state, CheckpointState.INVALID)
        self.assertFalse(result.verification_eligible)

    def test_nonboolean_uncertainty_flag_rejected(self):
        result = self.classify(publication_uncertain=0)
        self.assertEqual(result.state, CheckpointState.INVALID)
        self.assertFalse(result.verification_eligible)

    def test_matching_evidence(self):
        result = self.classify()
        self.assertEqual(result.state, CheckpointState.VERIFIED)
        self.assertTrue(result.verification_eligible)

    def test_missing_anchor(self):
        result = self.classify(anchor_sequence=None)
        self.assertEqual(result.state, CheckpointState.MISSING)
        self.assertFalse(result.verification_eligible)

    def test_unauthenticated_anchor(self):
        result = self.classify(anchor_authenticated=False)
        self.assertEqual(result.state, CheckpointState.INVALID)
        self.assertFalse(result.verification_eligible)

    def test_stale_anchor(self):
        result = self.classify(anchor_sequence=1)
        self.assertEqual(result.state, CheckpointState.STALE)
        self.assertFalse(result.verification_eligible)

    def test_future_anchor(self):
        result = self.classify(anchor_sequence=3)
        self.assertEqual(result.state, CheckpointState.DIVERGENT)
        self.assertFalse(result.verification_eligible)

    def test_digest_mismatch(self):
        result = self.classify(anchor_digest=OTHER)
        self.assertEqual(result.state, CheckpointState.DIVERGENT)
        self.assertFalse(result.verification_eligible)

    def test_uncertain_publication(self):
        result = self.classify(publication_uncertain=True)
        self.assertEqual(result.state, CheckpointState.UNCERTAIN)
        self.assertFalse(result.verification_eligible)

    def test_invalid_sequence(self):
        result = self.classify(journal_sequence=True)
        self.assertEqual(result.state, CheckpointState.INVALID)
        self.assertFalse(result.verification_eligible)

    def test_invalid_digest(self):
        result = self.classify(journal_digest="not-hex")
        self.assertEqual(result.state, CheckpointState.INVALID)
        self.assertFalse(result.verification_eligible)

    def test_no_evidence_is_never_eligible(self):
        result = self.classify(
            anchor_sequence=None,
            anchor_digest=None,
            anchor_authenticated=False,
        )
        self.assertFalse(result.verification_eligible)


if __name__ == "__main__":
    unittest.main()
