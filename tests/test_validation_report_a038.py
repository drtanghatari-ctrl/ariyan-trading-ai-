import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.validation_plan import freeze_plan
from test_validation_evaluation_a037 import FIXTURE, FIXTURE_START
from test_validation_plan_a036 import specification


class ValidationReportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.plan_path = root / "plan.json"
        self.report_path = root / "report.json"
        self.csv_path = root / "candles.csv"
        self.csv_path.write_bytes(FIXTURE.read_bytes())
        self.spec = specification(FIXTURE_START)
        self.plan = freeze_plan(self.spec, created_at_ms=0)
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.command = [
            sys.executable, "-m", "ariyan_trading.validation_evaluation",
            "--plan", self.plan_path, "--csv", self.csv_path,
        ]
        result = self.run_cli("--output", self.report_path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.saved = self.report_path.read_bytes()

    def run_cli(self, *args):
        return subprocess.run([*self.command, *args], capture_output=True)

    def verify(self):
        return self.run_cli(
            "--verify-report", self.report_path,
            "--expected-plan-sha256", self.plan["plan_sha256"],
        )

    def test_reproduces_a037_report_and_preserves_outcome(self):
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(self.saved)
        outcome = b"CRITERIA_MET" if report["criteria_met"] else b"CRITERIA_NOT_MET"
        self.assertEqual(result.stdout.splitlines(), [b"REPORT_REPRODUCED", outcome])
        self.assertEqual(self.report_path.read_bytes(), self.saved)

    def test_rejects_modified_report_and_changed_candle_bytes(self):
        report = json.loads(self.saved)
        report["criteria_met"] = not report["criteria_met"]
        for candidate in (json.dumps(report).encode(), self.saved + b" "):
            with self.subTest(candidate_length=len(candidate)):
                self.report_path.write_bytes(candidate)
                result = self.verify()
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"differs from the reproduced report", result.stderr)
                self.assertEqual(self.report_path.read_bytes(), candidate)

        self.report_path.write_bytes(self.saved)
        raw = self.csv_path.read_bytes()
        old_ending, new_ending = (b"\r\n", b"\n") if b"\r\n" in raw else (b"\n", b"\r\n")
        self.csv_path.write_bytes(raw.replace(old_ending, new_ending))
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"differs from the reproduced report", result.stderr)

    def test_requires_external_fingerprint_and_rejects_a_refrozen_plan(self):
        missing = self.run_cli("--verify-report", self.report_path)
        self.assertEqual(missing.returncode, 2)
        self.assertIn(b"must be used together", missing.stderr)

        self.spec["criteria"]["max_close_drawdown_pct"] = "7"
        alternate = freeze_plan(self.spec, created_at_ms=0)
        self.plan_path.write_text(json.dumps(alternate), encoding="utf-8")
        self.csv_path.unlink()
        result = self.verify()
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"separately recorded fingerprint", result.stderr)
