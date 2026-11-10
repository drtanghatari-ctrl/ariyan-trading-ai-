import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading.ledger_identity import new_ledger_identity
from ariyan_trading.paper_execution_state import (
    create_pinned_paper_execution_state, read_paper_execution_state,
)
from ariyan_trading.paper_state_escalation import VERSION, escalation_payload, prepare_paper_escalation


class PaperStateEscalationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.current = root / "current.json"
        self.successor = root / "successor.json"
        self.identity = new_ledger_identity()
        self.key = b"disposable-a052-test-key-only!!!"
        self.signer = Ed25519PrivateKey.generate()
        self.operator_key = self.signer.public_key().public_bytes_raw()
        self.pin = create_pinned_paper_execution_state(
            self.current, self.identity, "NORMAL", key=self.key,
        )
        self.intent = self.intent_for(self.pin, "STOP")

    def intent_for(self, pin, target):
        return {
            "version": VERSION, "ledger_identity": self.identity,
            "current_state_sha256": pin, "target_state": target, "expires_at_ms": 100,
        }

    def prepare(self, intent=None, **overrides):
        intent = self.intent if intent is None else intent
        args = {
            "signature": self.signer.sign(escalation_payload(intent)),
            "ledger_identity": self.identity, "expected_current_sha256": self.pin,
            "checkpoint_key": self.key, "operator_public_key": self.operator_key, "as_of_ms": 99,
        }
        args.update(overrides)
        return prepare_paper_escalation(self.current, self.successor, intent, **args)

    def test_signed_escalation_creates_successor_and_keeps_current_file(self):
        before = self.current.read_bytes()
        successor_pin = self.prepare()
        self.assertEqual(self.current.read_bytes(), before)
        self.assertEqual(successor_pin, hashlib.sha256(self.successor.read_bytes()).hexdigest())
        self.assertEqual(read_paper_execution_state(
            self.successor, self.identity, key=self.key, expected_sha256=successor_pin,
        ), "STOP")
        with self.assertRaises(FileExistsError):
            self.prepare()

    def test_wrong_signer_changed_target_expiry_and_wrong_pin_leave_no_successor(self):
        signature = self.signer.sign(escalation_payload(self.intent))
        other_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        cases = [
            (self.intent, {"operator_public_key": other_key}, "Invalid operator"),
            ({**self.intent, "target_state": "FREEZE"}, {"signature": signature}, "Invalid operator"),
            (self.intent, {"as_of_ms": 100}, "expired"),
            (self.intent, {"expected_current_sha256": "0" * 64}, "retained pin"),
            ({**self.intent, "ledger_identity": new_ledger_identity()}, {}, "different ledger"),
        ]
        for intent, overrides, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                self.prepare(intent, **overrides)
            self.assertFalse(self.successor.exists())

    def test_stop_can_escalate_to_freeze_but_freeze_cannot_relax(self):
        self.current.unlink()
        self.pin = create_pinned_paper_execution_state(
            self.current, self.identity, "STOP", key=self.key,
        )
        freeze_pin = self.prepare(self.intent_for(self.pin, "FREEZE"))
        self.current, self.successor = self.successor, self.current
        self.pin = freeze_pin
        before = self.current.read_bytes()
        with self.assertRaisesRegex(ValueError, "more restrictive"):
            self.prepare(self.intent_for(self.pin, "STOP"))
        self.assertEqual(self.current.read_bytes(), before)

    def test_restored_current_state_fails_the_pin_before_creating_successor(self):
        self.current.unlink()
        create_pinned_paper_execution_state(self.current, self.identity, "STOP", key=self.key)
        with self.assertRaisesRegex(ValueError, "differs from the expected SHA-256"):
            self.prepare()
        self.assertFalse(self.successor.exists())

    def test_uses_the_signed_intent_snapshot_throughout_preparation(self):
        def read_current(*args, **kwargs):
            self.intent["target_state"] = "FREEZE"
            return read_paper_execution_state(*args, **kwargs)

        with patch("ariyan_trading.paper_state_escalation.read_paper_execution_state",
                   side_effect=read_current):
            successor_pin = self.prepare()
        self.assertEqual(read_paper_execution_state(
            self.successor, self.identity, key=self.key, expected_sha256=successor_pin,
        ), "STOP")
