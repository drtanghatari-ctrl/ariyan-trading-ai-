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


class ValidationTimestampPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        plan_path = root / "plan.json"
        self.report_path = root / "report.json"
        self.plan = freeze_plan(specification(FIXTURE_START), created_at_ms=0)
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.receipt = root / "receipt.tsr"
        self.ca = root / "ca.pem"
        self.common = ["--plan", str(plan_path), "--csv", str(FIXTURE)]
        self.output = ["--output", str(self.report_path)]
        self.verify = [
            "--verify-report", str(self.report_path),
            "--expected-plan-sha256", self.plan["plan_sha256"],
        ]
        self.timestamp = [
            "--timestamp-receipt", str(self.receipt), "--timestamp-ca-file", str(self.ca),
            "--expected-timestamp-ca-sha256", "a" * 64,
        ]

    def test_records_timestamp_and_requires_the_same_receipt_on_reproduction(self):
        check_result = {
            "status": "RFC3161_PRE_WINDOW_TIMESTAMP_VERIFIED",
            "plan_sha256": self.plan["plan_sha256"],
            "signed_at_ms": 1, "receipt_sha256": "b" * 64, "ca_file_sha256": "a" * 64,
        }
        with patch.object(
            validation_evaluation, "verify_timestamp", return_value=check_result,
        ) as check, redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([
                *self.common, *self.output, *self.timestamp,
            ]), 0)
            check.assert_called_once_with(
                self.plan, self.receipt, self.ca, expected_ca_sha256="a" * 64,
                tsa_cert_path=None,
            )
            saved = self.report_path.read_bytes()
            report = json.loads(saved)
            self.assertEqual(report["version"], "ARIYAN-A046-VALIDATION-EVALUATION-V1")
            self.assertEqual(report["plan_timestamp_check"], check_result)
            self.assertFalse(report["plan_publication_time_verified"])
            self.assertEqual(validation_evaluation.main([
                *self.common, *self.verify, *self.timestamp,
            ]), 0)

            check.return_value = {**check_result, "receipt_sha256": "c" * 64}
            self.assert_rejected([*self.verify, *self.timestamp], "differs from the reproduced report")
            self.assert_rejected(self.verify, "differs from the reproduced report")
            self.assertEqual(self.report_path.read_bytes(), saved)

    def test_invalid_timestamp_and_incomplete_options_stop_before_candle_read(self):
        with patch.object(
            validation_evaluation, "verify_timestamp", side_effect=ValueError("Invalid receipt"),
        ) as check, patch.object(validation_evaluation, "load_candles") as candles:
            self.assert_rejected([*self.output, *self.timestamp[:-2]], "must be used together")
            self.assert_rejected([*self.output, "--timestamp-tsa-cert", str(self.ca)],
                                 "must be used together")
            check.assert_not_called()
            for mode in (self.output, self.verify):
                self.assert_rejected([*mode, *self.timestamp], "Invalid receipt")
            candles.assert_not_called()
            self.assertFalse(self.report_path.exists())

    def assert_rejected(self, options, message):
        with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
            validation_evaluation.main([*self.common, *options])
        self.assertEqual(error.exception.code, 2)
        self.assertIn(message, stderr.getvalue())
