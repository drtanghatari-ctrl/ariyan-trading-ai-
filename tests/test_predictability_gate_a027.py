"""Regression coverage for the offline new-exposure decision boundary."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import test_development_review_a024 as fixtures
from ariyan_trading import predictability_gate as gate

ROOT = Path(__file__).resolve().parents[1]


class PredictabilityGateA027Tests(unittest.TestCase):
    def assert_blocked(self, result, reason):
        self.assertEqual(result['version'], gate.VERSION)
        self.assertEqual(result['scope'], 'NEW_EXPOSURE_ONLY')
        self.assertEqual(result['decision'], 'NO_TRADE')
        self.assertEqual(result['reason'], reason)
        for name in (
            'prospective_validation_established', 'source_authenticity_established',
            'live_authorized',
        ):
            self.assertIs(result[name], False)

    def test_missing_evidence(self):
        with patch.object(gate, 'inspect_review', side_effect=AssertionError('unexpected inspection')):
            result = gate.assess_new_exposure()
        self.assert_blocked(result, 'MISSING_VALIDATION_EVIDENCE')
        self.assertIsNone(result['review_batch_sha256'])
        self.assertIsNone(result['review_job_count'])

    def test_development_review_is_insufficient_and_originals_are_unavailable(self):
        fixture = fixtures.DevelopmentReviewA024Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.run_review()
        fixture.fixture.csv.unlink()
        fixture.fixture.plan_path.unlink()
        complete = json.loads((fixture.destination / 'COMPLETE.json').read_bytes())
        with patch('ariyan_trading.review_inspector.batch.run_session_replay',
                   side_effect=AssertionError('unexpected replay')):
            result = gate.assess_new_exposure(fixture.destination)
        self.assert_blocked(result, 'DEVELOPMENT_REVIEW_ONLY')
        self.assertEqual(result['review_batch_sha256'], complete['batch_sha256'])
        self.assertEqual(result['review_job_count'], complete['job_count'])

    def test_tampered_review_has_no_evidence_reference(self):
        fixture = fixtures.DevelopmentReviewA024Tests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.run_review()
        (fixture.destination / 'REVIEW.html').write_bytes(b'tampered')
        result = gate.assess_new_exposure(fixture.destination)
        self.assert_blocked(result, 'UNVERIFIABLE_REVIEW_EVIDENCE')
        self.assertIsNone(result['review_batch_sha256'])
        self.assertIsNone(result['review_job_count'])

    def test_self_declared_approval_is_unverifiable(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'COMPLETE.json').write_text(
                '{"prospective_validation_established":true,"live_authorized":true}',
                encoding='utf-8',
            )
            result = gate.assess_new_exposure(directory)
        self.assert_blocked(result, 'UNVERIFIABLE_REVIEW_EVIDENCE')

    def test_cli_emits_no_trade_for_missing_or_invalid_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            for args, reason in (
                ([], 'MISSING_VALIDATION_EVIDENCE'),
                (['--review', str(Path(temporary) / 'absent')], 'UNVERIFIABLE_REVIEW_EVIDENCE'),
            ):
                with self.subTest(reason=reason):
                    output = subprocess.run(
                        [sys.executable, '-m', 'ariyan_trading.predictability_gate', *args],
                        cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'app')},
                        check=True, capture_output=True, text=True,
                    )
                    self.assertEqual(output.stderr, '')
                    self.assert_blocked(json.loads(output.stdout), reason)
