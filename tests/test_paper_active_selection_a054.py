import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import paper_entry
from ariyan_trading.ledger_identity import new_ledger_identity
from ariyan_trading.paper_active_selection import create_paper_active_selection
from ariyan_trading.paper_execution_controller import PaperExecutionController
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading.paper_state_escalation import VERSION, escalation_payload


class PaperActiveSelectionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.initial = root / "normal.json"
        self.freeze = root / "freeze.json"
        self.selector = root / "active.json"
        self.anchor = root / "anchor.json"
        self.ledger = SimpleNamespace(ledger_identity=new_ledger_identity())
        self.key = b"disposable-a054-test-key-only!!!"
        self.signer = Ed25519PrivateKey.generate()
        self.pin = create_pinned_paper_execution_state(
            self.initial, self.ledger.ledger_identity, "NORMAL", key=self.key,
        )
        create_paper_active_selection(
            self.selector, self.initial, ledger_identity=self.ledger.ledger_identity,
            expected_state_sha256=self.pin, checkpoint_key=self.key,
        )
        self.intent = {
            "version": VERSION, "ledger_identity": self.ledger.ledger_identity,
            "current_state_sha256": self.pin, "target_state": "FREEZE",
            "expires_at_ms": time.time_ns() // 1_000_000 + 60_000,
        }
        self.signature = self.signer.sign(escalation_payload(self.intent))

    def reopen(self, pin):
        return PaperExecutionController.reopen(
            self.selector, ledger_identity=self.ledger.ledger_identity,
            expected_state_sha256=pin, checkpoint_key=self.key,
            operator_public_key=self.signer.public_key().public_bytes_raw(),
        )

    def sell(self, controller):
        return controller.execute(self.ledger, "SELL", "exit", "1", "10.00",
                                  anchor_path=self.anchor)

    def test_recovers_freeze_and_rejects_restored_authentic_selector(self):
        old_selector = self.selector.read_bytes()
        controller = self.reopen(self.pin)
        freeze_pin = controller.activate_escalation(self.freeze, self.intent, self.signature)
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                self.sell(self.reopen(freeze_pin))
            with self.assertRaisesRegex(ValueError, "retained pin"):
                self.reopen(self.pin)
            self.selector.write_bytes(old_selector)
            with self.assertRaisesRegex(ValueError, "retained pin"):
                self.reopen(freeze_pin)
            with self.assertRaisesRegex(ValueError, "changed outside"):
                self.sell(controller)
            writer.assert_not_called()

    def test_missing_tampered_or_unavailable_state_has_no_fallback(self):
        controller = self.reopen(self.pin)
        freeze_pin = controller.activate_escalation(self.freeze, self.intent, self.signature)
        valid = self.selector.read_bytes()
        self.selector.write_bytes(valid + b" ")
        with self.assertRaisesRegex(ValueError, "authentication"):
            self.reopen(freeze_pin)
        self.selector.write_bytes(valid)
        self.freeze.unlink()
        with self.assertRaises(FileNotFoundError):
            self.reopen(freeze_pin)
        self.selector.unlink()
        with self.assertRaises(FileNotFoundError):
            self.reopen(freeze_pin)

    def test_failed_selector_replacement_keeps_previous_selection(self):
        controller = self.reopen(self.pin)
        before = self.selector.read_bytes()
        with patch("ariyan_trading.paper_active_selection.os.replace",
                   side_effect=OSError("publication failed")):
            with self.assertRaisesRegex(OSError, "publication failed"):
                controller.activate_escalation(self.freeze, self.intent, self.signature)
        self.assertEqual(self.selector.read_bytes(), before)
        self.assertTrue(self.freeze.is_file())
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            self.assertIs(self.sell(self.reopen(self.pin)), writer.return_value)
            writer.assert_called_once()
