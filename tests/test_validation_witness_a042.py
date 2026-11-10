import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading.validation_plan import freeze_plan
from ariyan_trading.validation_witness import VERSION, verify_witness_receipt, witness_payload
from test_validation_plan_a036 import specification


class ValidationWitnessTests(unittest.TestCase):
    def setUp(self):
        self.plan = freeze_plan(specification(), created_at_ms=10)
        self.signer = Ed25519PrivateKey.generate()
        self.key = self.signer.public_key().public_bytes_raw()
        self.receipt = self.signed_receipt(self.plan["plan_sha256"], 10)

    def signed_receipt(self, digest, observed):
        payload = f"ARIYAN-A042-PLAN-WITNESS-V1\n{digest}\n{observed}\n".encode("ascii")
        return {
            "version": VERSION, "plan_sha256": digest, "observed_at_ms": observed,
            "signature_hex": self.signer.sign(payload).hex(),
        }

    def verify(self, receipt):
        return verify_witness_receipt(self.plan, receipt, witness_public_key_hex=self.key.hex())

    def test_verifies_exact_plan_and_independently_supplied_key(self):
        result = self.verify(self.receipt)
        self.assertEqual(result["status"], "SIGNED_PRE_WINDOW_RECEIPT_VERIFIED")
        self.assertEqual(result["plan_sha256"], self.plan["plan_sha256"])
        self.assertEqual(result["witness_public_key_sha256"], hashlib.sha256(self.key).hexdigest())
        self.assertEqual(result["observed_at_ms"], 10)
        self.assertEqual(
            witness_payload("a" * 64, 10), b"ARIYAN-A042-PLAN-WITNESS-V1\n" + b"a" * 64 + b"\n10\n",
        )

    def test_rejects_wrong_key_changed_time_and_substituted_plan(self):
        other_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()
        with self.assertRaisesRegex(ValueError, "Invalid witness signature"):
            verify_witness_receipt(self.plan, self.receipt, witness_public_key_hex=other_key)
        with self.assertRaisesRegex(ValueError, "Invalid witness signature"):
            self.verify({**self.receipt, "observed_at_ms": 11})
        with self.assertRaisesRegex(ValueError, "different plan"):
            self.verify(self.signed_receipt("b" * 64, 10))

    def test_rejects_out_of_window_and_malformed_receipts(self):
        for value in (9, self.plan["spec"]["window"]["start_ms"]):
            with self.subTest(observed_at_ms=value), self.assertRaisesRegex(ValueError, "Witness time"):
                self.verify(self.signed_receipt(self.plan["plan_sha256"], value))
        for changes in (
            {"observed_at_ms": True},
            {"observed_at_ms": 10.0},
            {"version": "OTHER"},
            {"signature_hex": "00"},
            {"public_key": self.key.hex()},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.verify({**self.receipt, **changes})

    def test_cli_rejects_duplicate_keys_and_verifies_valid_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            receipt = Path(directory) / "receipt.json"
            plan.write_text(json.dumps(self.plan), encoding="utf-8")
            receipt.write_text(json.dumps(self.receipt), encoding="utf-8")
            command = [
                sys.executable, "-m", "ariyan_trading.validation_witness",
                "--plan", plan, "--receipt", receipt, "--witness-public-key-hex", self.key.hex(),
            ]
            success = subprocess.run(command, capture_output=True)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(json.loads(success.stdout), self.verify(self.receipt))
            receipt.write_text('{"version":"a","version":"b"}', encoding="utf-8")
            failure = subprocess.run(command, capture_output=True)
            self.assertEqual(failure.returncode, 2)
            self.assertIn(b"Duplicate JSON key", failure.stderr)
