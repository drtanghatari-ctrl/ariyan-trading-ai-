import hashlib
import json
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from ariyan_trading.validation_plan import freeze_plan
from ariyan_trading.validation_timestamp import verify_plan_timestamp
from test_validation_plan_a036 import HOUR, specification


@unittest.skipUnless(shutil.which("openssl"), "OpenSSL command is required")
class ValidationTimestampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.root = Path(directory.name)
        cls.openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", "ca.key", "-out", "ca.pem", "-subj", "/CN=ATAI Test CA",
                    "-days", "2", "-addext", "basicConstraints=critical,CA:TRUE",
                    "-addext", "keyUsage=critical,keyCertSign")
        cls.openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "tsa.key",
                    "-out", "tsa.csr", "-subj", "/CN=ATAI Test TSA")
        (cls.root / "extensions").write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=critical,timeStamping\n", encoding="ascii",
        )
        cls.openssl("x509", "-req", "-in", "tsa.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
                    "-CAcreateserial", "-out", "tsa.pem", "-days", "2", "-extfile", "extensions")
        (cls.root / "serial").write_text("01\n", encoding="ascii")
        (cls.root / "tsa.cnf").write_text(
            "[tsa]\ndefault_tsa = local\n[local]\nserial = serial\n"
            "signer_cert = tsa.pem\nsigner_key = tsa.key\nsigner_digest = sha256\n"
            "default_policy = 1.2.3.4\ndigests = sha256\nclock_precision_digits = 3\n"
            "ess_cert_id_chain = no\ness_cert_id_alg = sha256\n",
            encoding="ascii",
        )
        cls.ca_hash = hashlib.sha256((cls.root / "ca.pem").read_bytes()).hexdigest()

    @classmethod
    def openssl(cls, *args):
        result = subprocess.run(
            ["openssl", *args], cwd=cls.root, capture_output=True, text=True, timeout=15,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    def issue(self, start_ms):
        plan = freeze_plan(specification(start_ms), created_at_ms=0)
        (self.root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
        self.openssl("ts", "-query", "-sha256", "-digest", plan["plan_sha256"], "-cert",
                     "-out", "query.tsq")
        self.openssl("ts", "-reply", "-config", "tsa.cnf", "-queryfile", "query.tsq",
                     "-out", "receipt.tsr")
        return plan

    def verify(self, ca_hash=None):
        return verify_plan_timestamp(
            self.root / "plan.json", self.root / "receipt.tsr", self.root / "ca.pem",
            expected_ca_sha256=self.ca_hash if ca_hash is None else ca_hash,
        )

    def test_verifies_signed_pre_window_receipt_and_exact_digest(self):
        start = (time.time_ns() // 1_000_000 // HOUR + 2) * HOUR
        plan = self.issue(start)
        result = self.verify()
        self.assertEqual(result["status"], "RFC3161_PRE_WINDOW_TIMESTAMP_VERIFIED")
        self.assertLess(result["signed_at_ms"], start)
        self.assertEqual(result["plan_sha256"], plan["plan_sha256"])
        self.assertEqual(result["receipt_sha256"], hashlib.sha256(
            (self.root / "receipt.tsr").read_bytes(),
        ).hexdigest())

        wrong = freeze_plan(specification(start + HOUR), created_at_ms=0)
        (self.root / "plan.json").write_text(json.dumps(wrong), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "timestamp verify failed"):
            self.verify()

    def test_rejects_wrong_ca_pin_and_late_signed_receipt(self):
        start = (time.time_ns() // 1_000_000 // HOUR - 1) * HOUR
        self.issue(start)
        with self.assertRaisesRegex(ValueError, "expected SHA-256"):
            self.verify("0" * 64)
        with self.assertRaisesRegex(ValueError, "before the window"):
            self.verify()
