import json
import os
import subprocess
import sys
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
from ariyan_trading.paper_active_selection import create_paper_active_selection
from ariyan_trading.paper_execution_controller import PaperExecutionController
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading.paper_state_escalation import VERSION, escalation_payload


def _wait_for_file(path, timeout):
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def _hold_order():
    root = Path(sys.argv[1])
    configuration = json.loads((root / "child.json").read_text(encoding="utf-8"))
    for name in ("checkpoint_key", "operator_public_key"):
        configuration[name] = bytes.fromhex(configuration[name])
    controller = PaperExecutionController.reopen(root / "active.json", **configuration)
    ledger = SimpleNamespace(ledger_identity=configuration["ledger_identity"])

    def hold_writer(*args, **kwargs):
        (root / "entered").touch()
        if not _wait_for_file(root / "release", 15):
            raise AssertionError("Test did not release the process holding the order")

    with patch.object(paper_entry, "execute_checkpointed_trade", side_effect=hold_writer):
        controller.execute(ledger, "SELL", "old-exit", "1", "10.00",
                           anchor_path=root / "anchor.json")


class PaperProcessLockTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        state = root / "normal.json"
        self.selector = root / "active.json"
        self.successor = root / "freeze.json"
        self.anchor = root / "anchor.json"
        identity = new_ledger_identity()
        key = b"disposable-a055-test-key-only!!!"
        signer = Ed25519PrivateKey.generate()
        pin = create_pinned_paper_execution_state(state, identity, "NORMAL", key=key)
        self.configuration = {
            "ledger_identity": identity, "expected_state_sha256": pin,
            "checkpoint_key": key, "operator_public_key": signer.public_key().public_bytes_raw(),
        }
        self.ledger = SimpleNamespace(ledger_identity=identity)
        create_paper_active_selection(
            self.selector, state, ledger_identity=identity,
            expected_state_sha256=pin, checkpoint_key=key,
        )
        self.controller = PaperExecutionController.reopen(self.selector, **self.configuration)
        self.intent = {
            "version": VERSION, "ledger_identity": identity, "current_state_sha256": pin,
            "target_state": "FREEZE", "expires_at_ms": time.time_ns() // 1_000_000 + 60_000,
        }
        self.signature = signer.sign(escalation_payload(self.intent))

    def sell(self, controller):
        return controller.execute(
            self.ledger, "SELL", "exit", "1", "10.00", anchor_path=self.anchor,
        )

    def test_cross_process_order_blocks_escalation_and_stale_controller_cannot_sell(self):
        stale = PaperExecutionController.reopen(self.selector, **self.configuration)
        root = self.selector.parent
        entered, release = root / "entered", root / "release"
        transition_started = Event()
        (root / "child.json").write_text(json.dumps({
            name: value.hex() if isinstance(value, bytes) else value
            for name, value in self.configuration.items()
        }), encoding="utf-8")
        project = Path(__file__).resolve().parents[1]
        python_path = os.pathsep.join(str(project / name) for name in ("app", "tests"))

        def activate():
            transition_started.set()
            return self.controller.activate_escalation(self.successor, self.intent, self.signature)

        process = subprocess.Popen(
            [sys.executable, "-c",
             "from test_paper_process_lock_a055 import _hold_order; _hold_order()", str(root)],
            cwd=project, env={**os.environ, "PYTHONPATH": python_path},
        )
        try:
            self.assertTrue(_wait_for_file(entered, 10), f"Child exit code: {process.poll()}")
            with ThreadPoolExecutor(max_workers=1) as pool:
                transition = pool.submit(activate)
                try:
                    self.assertTrue(transition_started.wait(5))
                    with self.assertRaises(TimeoutError):
                        transition.result(timeout=0.2)
                    self.assertFalse(self.successor.exists())
                finally:
                    release.touch()
                pin = transition.result(timeout=10)
            self.assertEqual(process.wait(timeout=5), 0)
            reopened = PaperExecutionController.reopen(
                self.selector, **{**self.configuration, "expected_state_sha256": pin},
            )
            with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
                with self.assertRaisesRegex(ValueError, "changed outside"):
                    self.sell(stale)
                with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                    self.sell(reopened)
                writer.assert_not_called()
        finally:
            release.touch()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def test_lock_timeout_blocks_orders_and_escalation(self):
        with patch("ariyan_trading.paper_execution_controller.initialization_lock",
                   side_effect=TimeoutError("lock timed out")), \
                patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                self.sell(self.controller)
            with self.assertRaisesRegex(TimeoutError, "timed out"):
                self.controller.activate_escalation(self.successor, self.intent, self.signature)
            self.assertFalse(self.successor.exists())
            writer.assert_not_called()
