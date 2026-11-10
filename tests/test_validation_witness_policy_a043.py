import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import validation_evaluation
from ariyan_trading.validation_plan import freeze_plan
from ariyan_trading.validation_witness import VERSION, witness_payload
from test_validation_evaluation_a037 import FIXTURE, FIXTURE_START
from test_validation_plan_a036 import specification


class ValidationWitnessPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        plan_path = root / "plan.json"
        self.report_path = root / "report.json"
        self.receipt_path = root / "receipt.json"
        plan = freeze_plan(specification(FIXTURE_START), created_at_ms=0)
        digest = plan["plan_sha256"]
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        signer = Ed25519PrivateKey.generate()
        self.key = signer.public_key().public_bytes_raw().hex()
        self.receipt = {
            "version": VERSION, "plan_sha256": digest, "observed_at_ms": 1,
            "signature_hex": signer.sign(witness_payload(digest, 1)).hex(),
        }
        self.write_receipt()
        self.common = ["--plan", str(plan_path), "--csv", str(FIXTURE)]
        self.output = ["--output", str(self.report_path)]
        self.verify = ["--verify-report", str(self.report_path), "--expected-plan-sha256", digest]
        self.witness = ["--witness-receipt", str(self.receipt_path),
                        "--witness-public-key-hex", self.key]

    def write_receipt(self):
        self.receipt_path.write_text(json.dumps(self.receipt), encoding="utf-8")

    def test_valid_receipt_allows_creation_and_byte_identical_reproduction(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(validation_evaluation.main([*self.common, *self.output]), 0)
            baseline = self.report_path.read_bytes()
            self.report_path.unlink()
            self.assertEqual(validation_evaluation.main([
                *self.common, *self.output, *self.witness,
            ]), 0)
            self.assertEqual(self.report_path.read_bytes(), baseline)
            self.assertEqual(validation_evaluation.main([
                *self.common, *self.verify, *self.witness,
            ]), 0)

    def test_invalid_receipt_blocks_both_modes_before_candle_read(self):
        self.receipt["observed_at_ms"] = 2
        self.write_receipt()
        for mode in (self.output, self.verify):
            with self.subTest(mode=mode[0]):
                self.assert_blocked([*mode, *self.witness], "Invalid witness signature")

    def test_requires_both_receipt_and_expected_key(self):
        for partial in (self.witness[:2], self.witness[2:]):
            with self.subTest(option=partial[0]):
                self.assert_blocked([*self.output, *partial], "must be used together")

    def assert_blocked(self, args, message):
        with patch.object(validation_evaluation, "load_candles") as load:
            with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
                validation_evaluation.main([*self.common, *args])
            self.assertEqual(error.exception.code, 2)
            self.assertIn(message, stderr.getvalue())
            load.assert_not_called()
            self.assertFalse(self.report_path.exists())
