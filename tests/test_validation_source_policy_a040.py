import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import validation_evaluation
from ariyan_trading.validation_plan import freeze_plan
from test_validation_evaluation_a037 import FIXTURE, FIXTURE_START
from test_validation_plan_a036 import specification


class ValidationSourcePolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.plan_path = root / "plan.json"
        self.report_path = root / "report.json"
        self.plan = freeze_plan(specification(FIXTURE_START), created_at_ms=0)
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.common = ["--plan", str(self.plan_path), "--csv", str(FIXTURE)]
        self.output = ["--output", str(self.report_path)]
        self.verify = [
            "--verify-report", str(self.report_path),
            "--expected-plan-sha256", self.plan["plan_sha256"],
        ]
        self.root = Path(validation_evaluation.__file__).resolve().parents[2]

    def test_source_match_allows_creation_and_reproduction(self):
        with patch.object(validation_evaluation, "verify_engine_sources") as check:
            with redirect_stdout(io.StringIO()) as creation:
                self.assertEqual(validation_evaluation.main([
                    *self.common, *self.output, "--require-engine-source",
                ]), 0)
            check.assert_called_once_with(self.root, self.plan["spec"]["code_commit"])
            check.reset_mock()
            saved = self.report_path.read_bytes()

            with redirect_stdout(io.StringIO()) as reproduction:
                self.assertEqual(validation_evaluation.main([
                    *self.common, *self.verify, "--require-engine-source",
                ]), 0)
            check.assert_called_once_with(self.root, self.plan["spec"]["code_commit"])
            self.assertEqual(
                reproduction.getvalue(), "REPORT_REPRODUCED\n" + creation.getvalue(),
            )
            self.assertEqual(self.report_path.read_bytes(), saved)

    def test_source_mismatch_blocks_both_modes_before_candle_read(self):
        for mode in (self.output, self.verify):
            with self.subTest(mode=mode[0]):
                with patch.object(
                    validation_evaluation, "verify_engine_sources",
                    side_effect=ValueError("Source mismatch"),
                ), patch.object(validation_evaluation, "load_candles") as load:
                    with redirect_stderr(io.StringIO()) as stderr:
                        with self.assertRaises(SystemExit) as stopped:
                            validation_evaluation.main([
                                *self.common, *mode, "--require-engine-source",
                            ])
                    self.assertEqual(stopped.exception.code, 2)
                    self.assertIn("Source mismatch", stderr.getvalue())
                    load.assert_not_called()
                    self.assertFalse(self.report_path.exists())

    def test_existing_cli_behavior_does_not_call_git(self):
        with patch.object(validation_evaluation, "verify_engine_sources") as check:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validation_evaluation.main([*self.common, *self.output]), 0)
                self.assertEqual(validation_evaluation.main([*self.common, *self.verify]), 0)
            check.assert_not_called()
