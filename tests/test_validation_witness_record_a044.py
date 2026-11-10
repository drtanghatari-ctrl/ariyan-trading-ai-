import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import validation_evaluation
from ariyan_trading.validation_engine import ENGINE_PATHS
from ariyan_trading.validation_plan import freeze_plan
from ariyan_trading.validation_witness import VERSION, witness_payload
from test_validation_evaluation_a037 import FIXTURE, FIXTURE_START
from test_validation_plan_a036 import specification


class ValidationWitnessRecordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        plan_path = root / "plan.json"
        self.receipt_path = root / "receipt.json"
        self.report_path = root / "report.json"
        self.plan = freeze_plan(specification(FIXTURE_START), created_at_ms=0)
        self.digest = self.plan["plan_sha256"]
        plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.signer = Ed25519PrivateKey.generate()
        self.key = self.signer.public_key().public_bytes_raw()
        self.common = [
            "--plan", str(plan_path), "--csv", str(FIXTURE), "--record-witness-receipt",
        ]
        self.witness = [
            "--witness-receipt", str(self.receipt_path),
            "--witness-public-key-hex", self.key.hex(),
        ]
        self.output = ["--output", str(self.report_path)]
        self.verify = [
            "--verify-report", str(self.report_path), "--expected-plan-sha256", self.digest,
        ]

    def receipt(self, observed):
        return {
            "version": VERSION, "plan_sha256": self.digest, "observed_at_ms": observed,
            "signature_hex": self.signer.sign(witness_payload(self.digest, observed)).hex(),
        }

    def test_records_receipt_with_source_check_and_reproduces_after_reformatting(self):
        receipt = self.receipt(1)
        self.receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        options = [*self.common, *self.witness, "--record-engine-source"]
        with patch.object(
            validation_evaluation, "verify_engine_sources", return_value=ENGINE_PATHS,
        ), redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([*options, *self.output]), 0)
            saved = self.report_path.read_bytes()
            self.receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
            self.assertEqual(validation_evaluation.main([*options, *self.verify]), 0)

        report = json.loads(saved)
        self.assertEqual(report["version"], "ARIYAN-A044-VALIDATION-EVALUATION-V1")
        canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.assertEqual(report["witness_receipt_check"], {
            "version": VERSION,
            "status": "SIGNED_PRE_WINDOW_RECEIPT_VERIFIED",
            "plan_sha256": self.digest,
            "observed_at_ms": 1,
            "witness_public_key_sha256": hashlib.sha256(self.key).hexdigest(),
            "receipt_sha256": hashlib.sha256(canonical).hexdigest(),
        })
        self.assertEqual(report["engine_source_check"]["checked_paths"], list(ENGINE_PATHS))
        self.assertFalse(report["plan_publication_time_verified"])
        self.assertEqual(self.report_path.read_bytes(), saved)

    def test_substituting_another_valid_receipt_breaks_reproduction(self):
        options = [*self.common, *self.witness]
        self.receipt_path.write_text(json.dumps(self.receipt(1)), encoding="utf-8")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([*options, *self.output]), 0)
        saved = self.report_path.read_bytes()
        self.receipt_path.write_text(json.dumps(self.receipt(2)), encoding="utf-8")
        with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
            validation_evaluation.main([*options, *self.verify])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("differs from the reproduced report", stderr.getvalue())
        self.assertEqual(self.report_path.read_bytes(), saved)

    def test_record_mode_requires_witness_before_candle_read(self):
        with patch.object(validation_evaluation, "load_candles") as load:
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                validation_evaluation.main([*self.common, *self.output])
            self.assertEqual(error.exception.code, 2)
            self.assertIn("requires a witness receipt and key", stderr.getvalue())
            load.assert_not_called()
            self.assertFalse(self.report_path.exists())
