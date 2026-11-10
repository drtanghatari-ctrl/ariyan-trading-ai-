"""Cross-process rehearsal through the real paper checkpoint coordinator."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import closing
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import checkpoint_coordinator
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.paper_active_selection import create_paper_active_selection
from ariyan_trading.paper_entry import PaperExecutionDenied
from ariyan_trading.paper_execution_controller import PaperExecutionController
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading.paper_state_escalation import VERSION, escalation_payload
from ariyan_trading.trust_anchor import create_anchor, read_anchor, write_anchor
from test_paper_process_lock_a055 import _wait_for_file


def _sell_with_paused_publication(root):
    configuration = json.loads((root / "child.json").read_text(encoding="utf-8"))
    for name in ("checkpoint_key", "operator_public_key"):
        configuration[name] = bytes.fromhex(configuration[name])
    controller = PaperExecutionController.reopen(root / "active.json", **configuration)

    def publish(*args, **kwargs):
        (root / "publishing").touch()
        if not _wait_for_file(root / "release", 15):
            raise AssertionError("Test did not release checkpoint publication")
        return write_anchor(*args, **kwargs)

    with closing(DurableLedger(root / "ledger.sqlite", opening_cash="1000.00")) as ledger:
        with patch.object(checkpoint_coordinator, "write_anchor", side_effect=publish):
            result = controller.execute(
                ledger, "SELL", "in-progress", "1", "11.00", anchor_path=root / "anchor.json",
            )
        if result["sequence"] != 2:
            raise AssertionError("Child did not publish checkpoint sequence two")


@unittest.skipIf(os.name == "nt", "Requires native A006 anchor publication")
class PaperCheckpointRehearsalTests(unittest.TestCase):
    def test_real_sell_publishes_before_freeze_and_next_sell_cannot_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, anchor = root / "ledger.sqlite", root / "anchor.json"
            state, selector = root / "normal.json", root / "active.json"
            freeze = root / "freeze.json"
            key = b"disposable-a056-test-key-only!!!"
            signer = Ed25519PrivateKey.generate()

            with closing(DurableLedger(database, opening_cash="1000.00")) as ledger:
                with ledger.db:
                    ledger.db.execute("BEGIN")
                    digest = verify_protected_journal(ledger.db, ledger.opening_cash)
                write_anchor(anchor, create_anchor(0, digest, key), key)
                checkpoint_coordinator.execute_checkpointed_trade(
                    ledger, "BUY", "seed", "2", "10.00", anchor_path=anchor, key=key,
                )
                identity = ledger.ledger_identity

            pin = create_pinned_paper_execution_state(state, identity, "NORMAL", key=key)
            create_paper_active_selection(
                selector, state, ledger_identity=identity,
                expected_state_sha256=pin, checkpoint_key=key,
            )
            configuration = {
                "ledger_identity": identity, "expected_state_sha256": pin,
                "checkpoint_key": key, "operator_public_key": signer.public_key().public_bytes_raw(),
            }
            controller = PaperExecutionController.reopen(selector, **configuration)
            intent = {
                "version": VERSION, "ledger_identity": identity, "current_state_sha256": pin,
                "target_state": "FREEZE", "expires_at_ms": time.time_ns() // 1_000_000 + 60_000,
            }
            signature = signer.sign(escalation_payload(intent))
            freeze_pin = self.activate_during_publication(
                root, controller, freeze, intent, signature, configuration,
            )

            reopened = PaperExecutionController.reopen(
                selector, **{**configuration, "expected_state_sha256": freeze_pin},
            )
            with closing(DurableLedger(database, checkpoint_path=anchor, checkpoint_key=key)) as reader:
                self.assertEqual(reader.balances(), (Decimal("991.00"), Decimal("1")))
                self.assertEqual(read_anchor(anchor, key)[0], 2)

            with closing(DurableLedger(database, opening_cash="1000.00")) as ledger:
                before = tuple(ledger.db.iterdump()), anchor.read_bytes()
                statements = []
                ledger.db.set_trace_callback(statements.append)
                try:
                    with self.assertRaisesRegex(PaperExecutionDenied, "blocked by FREEZE"):
                        reopened.execute(
                            ledger, "SELL", "after-freeze", "1", "11.00", anchor_path=anchor,
                        )
                finally:
                    ledger.db.set_trace_callback(None)
                self.assertEqual(statements, [])
                self.assertEqual((tuple(ledger.db.iterdump()), anchor.read_bytes()), before)

    def activate_during_publication(self, root, controller, freeze, intent, signature, configuration):
        (root / "child.json").write_text(json.dumps({
            name: value.hex() if isinstance(value, bytes) else value
            for name, value in configuration.items()
        }), encoding="utf-8")
        project = Path(__file__).resolve().parents[1]
        python_path = os.pathsep.join(str(project / name) for name in ("app", "tests"))
        started = Event()

        def activate():
            started.set()
            return controller.activate_escalation(freeze, intent, signature)

        process = subprocess.Popen(
            [sys.executable, "-c",
             "from test_paper_checkpoint_rehearsal_a056 import _sell_with_paused_publication;"
             "from pathlib import Path; import sys; _sell_with_paused_publication(Path(sys.argv[1]))",
             str(root)],
            cwd=project, env={**os.environ, "PYTHONPATH": python_path},
        )
        release = root / "release"
        try:
            self.assertTrue(_wait_for_file(root / "publishing", 10), f"Child exit: {process.poll()}")
            self.assertEqual(read_anchor(root / "anchor.json", configuration["checkpoint_key"])[0], 1)
            with closing(sqlite3.connect((root / "ledger.sqlite").as_uri() + "?mode=ro",
                                         uri=True, timeout=2)) as reader:
                marker = reader.execute(
                    "SELECT value FROM ledger_meta WHERE key=?", (checkpoint_coordinator.PENDING,),
                ).fetchone()
                self.assertIsNotNone(marker)

            with ThreadPoolExecutor(max_workers=1) as pool:
                activation = pool.submit(activate)
                try:
                    self.assertTrue(started.wait(5))
                    with self.assertRaises(TimeoutError):
                        activation.result(timeout=0.2)
                    self.assertFalse(freeze.exists())
                finally:
                    release.touch()
                freeze_pin = activation.result(timeout=10)
            self.assertEqual(process.wait(timeout=5), 0)
            return freeze_pin
        finally:
            release.touch()
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
