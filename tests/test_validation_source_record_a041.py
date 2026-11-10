import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import validation_evaluation
from ariyan_trading.validation_engine import ENGINE_PATHS
from ariyan_trading.validation_plan import freeze_plan
from test_validation_evaluation_a037 import FIXTURE, FIXTURE_START
from test_validation_plan_a036 import specification


class ValidationSourceRecordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.plan_path = root / "plan.json"
        self.report_path = root / "report.json"
        self.plan = freeze_plan(specification(FIXTURE_START), created_at_ms=0)
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.common = [
            "--plan", str(self.plan_path), "--csv", str(FIXTURE), "--record-engine-source",
        ]
        self.output = ["--output", str(self.report_path)]
        self.verify = [
            "--verify-report", str(self.report_path),
            "--expected-plan-sha256", self.plan["plan_sha256"],
        ]

    def test_records_and_reproduces_the_source_scope(self):
        with patch.object(
            validation_evaluation, "verify_engine_sources", return_value=ENGINE_PATHS,
        ) as check, redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([*self.common, *self.output]), 0)
            saved = self.report_path.read_bytes()
            report = json.loads(saved)
            self.assertEqual(report["version"], "ARIYAN-A041-VALIDATION-EVALUATION-V1")
            self.assertEqual(report["declared_code_commit"], self.plan["spec"]["code_commit"])
            self.assertEqual(report["engine_source_check"], {
                "status": "LOCAL_SOURCE_BYTES_MATCH", "checked_paths": list(ENGINE_PATHS),
            })
            self.assertFalse(report["code_commit_verified"])
            self.assertFalse(report["live_authorized"])
            self.assertEqual(validation_evaluation.main([*self.common, *self.verify]), 0)
            self.assertEqual(self.report_path.read_bytes(), saved)
            self.assertEqual(check.call_count, 2)

            report["engine_source_check"]["checked_paths"].pop()
            self.report_path.write_bytes((json.dumps(report, sort_keys=True, indent=2) + "\n").encode("ascii"))
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                validation_evaluation.main([*self.common, *self.verify])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("differs from the reproduced report", stderr.getvalue())

    def test_record_mode_requires_source_match_before_candle_read(self):
        with patch.object(
            validation_evaluation, "verify_engine_sources", side_effect=ValueError("Source mismatch"),
        ), patch.object(validation_evaluation, "load_candles") as load:
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                validation_evaluation.main([*self.common, *self.output])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("Source mismatch", stderr.getvalue())
            load.assert_not_called()
            self.assertFalse(self.report_path.exists())
