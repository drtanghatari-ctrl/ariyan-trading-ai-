import hashlib
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import paper_entry
from ariyan_trading.ledger_identity import new_ledger_identity
from ariyan_trading.paper_execution_controller import PaperExecutionController
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading.paper_state_escalation import VERSION, escalation_payload


class PaperExecutionControllerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.initial = root / "normal.json"
        self.successor = root / "freeze.json"
        self.anchor = root / "anchor.json"
        self.ledger = SimpleNamespace(ledger_identity=new_ledger_identity())
        self.key = b"disposable-a053-test-key-only!!!"
        self.signer = Ed25519PrivateKey.generate()
        self.pin = create_pinned_paper_execution_state(
            self.initial, self.ledger.ledger_identity, "NORMAL", key=self.key,
        )
        self.controller = PaperExecutionController(
            self.initial, ledger_identity=self.ledger.ledger_identity,
            expected_state_sha256=self.pin, checkpoint_key=self.key,
            operator_public_key=self.signer.public_key().public_bytes_raw(),
        )
        self.intent = {
            "version": VERSION, "ledger_identity": self.ledger.ledger_identity,
            "current_state_sha256": self.pin, "target_state": "FREEZE",
            "expires_at_ms": time.time_ns() // 1_000_000 + 60_000,
        }
        self.signature = self.signer.sign(escalation_payload(self.intent))

    def sell(self):
        return self.controller.execute(
            self.ledger, "SELL", "exit", "1", "10.00", anchor_path=self.anchor,
        )

    def activate(self):
        return self.controller.activate_escalation(self.successor, self.intent, self.signature)

    def test_activation_changes_submission_policy_and_rejects_stale_intent(self):
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            self.assertIs(self.sell(), writer.return_value)
            next_pin = self.activate()
            self.assertEqual(next_pin, hashlib.sha256(self.successor.read_bytes()).hexdigest())
            with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                self.sell()
            with self.assertRaisesRegex(ValueError, "retained pin"):
                self.activate()
            writer.assert_called_once()

    def test_failed_activation_keeps_current_selection(self):
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaisesRegex(ValueError, "Invalid operator"):
                self.controller.activate_escalation(self.successor, self.intent, b"x" * 64)
            self.assertFalse(self.successor.exists())
            self.assertIs(self.sell(), writer.return_value)
            writer.assert_called_once()

    def test_activation_waits_for_an_in_progress_order(self):
        writer_entered = Event()
        release_writer = Event()
        transition_started = Event()

        def finish_order(*args, **kwargs):
            writer_entered.set()
            if not release_writer.wait(5):
                raise AssertionError("Test did not release the in-progress order")
            return "finished"

        def activate_after_signal():
            transition_started.set()
            return self.activate()

        with patch.object(paper_entry, "execute_checkpointed_trade", side_effect=finish_order) as writer:
            with ThreadPoolExecutor(max_workers=2) as pool:
                order = pool.submit(self.sell)
                try:
                    self.assertTrue(writer_entered.wait(5))
                    transition = pool.submit(activate_after_signal)
                    self.assertTrue(transition_started.wait(5))
                    with self.assertRaises(TimeoutError):
                        transition.result(timeout=0.15)
                    self.assertFalse(self.successor.exists())
                finally:
                    release_writer.set()
                self.assertEqual(order.result(timeout=5), "finished")
                transition.result(timeout=5)
            with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                self.sell()
            writer.assert_called_once()
