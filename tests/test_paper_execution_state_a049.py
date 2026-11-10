import os
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import paper_entry
from ariyan_trading.checkpoint_coordinator import execute_checkpointed_trade
from ariyan_trading.checkpoint_publication import PublicationState
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class PaperExecutionStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.anchor = root / "anchor.json"
        self.key = b"disposable-a049-test-key-only!!!"
        self.ledger = DurableLedger(root / "ledger.sqlite", opening_cash="1000.00")
        self.addCleanup(self.ledger.close)
        with self.ledger.db:
            self.ledger.db.execute("BEGIN")
            digest = verify_protected_journal(self.ledger.db, self.ledger.opening_cash)
        write_anchor(self.anchor, create_anchor(0, digest, self.key), self.key)
        execute_checkpointed_trade(
            self.ledger, "BUY", "seed", "2", "10.00", anchor_path=self.anchor, key=self.key,
        )

    def execute(self, action, state):
        return paper_entry.execute_governed_paper_trade(
            self.ledger, action, "order", "1", "10.00",
            anchor_path=self.anchor, key=self.key, execution_state=state,
        )

    def test_freeze_leaves_ledger_and_anchor_untouched(self):
        before = tuple(self.ledger.db.iterdump()), self.anchor.read_bytes()
        statements = []
        self.ledger.db.set_trace_callback(statements.append)
        try:
            with patch.object(paper_entry, "execute_checkpointed_trade") as writer, \
                    patch.object(paper_entry, "assess_new_exposure") as gate:
                for action in ("SELL", "BUY"):
                    with self.subTest(action=action):
                        with self.assertRaises(paper_entry.PaperExecutionDenied) as denied:
                            self.execute(action, "FREEZE")
                        self.assertEqual(denied.exception.execution_state, "FREEZE")
                        self.assertEqual(denied.exception.action, action)
                writer.assert_not_called()
                gate.assert_not_called()
        finally:
            self.ledger.db.set_trace_callback(None)
        self.assertEqual(statements, [])
        self.assertEqual((tuple(self.ledger.db.iterdump()), self.anchor.read_bytes()), before)

    def test_stop_denies_buy_and_allows_a_checkpointed_sell(self):
        with patch.object(paper_entry, "assess_new_exposure") as gate:
            with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by STOP"):
                self.execute("BUY", "STOP")
            result = self.execute("SELL", "STOP")
            gate.assert_not_called()
        self.assertIs(result["state"], PublicationState.DURABLE)
        self.assertEqual(result["sequence"], 2)
        self.assertEqual(self.ledger.balances(), (Decimal("990.00"), Decimal("1")))

    def test_unknown_state_never_reaches_the_writer(self):
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            for state in (None, "freeze", "RESUME"):
                with self.subTest(state=state), self.assertRaisesRegex(ValueError, "Unsupported"):
                    self.execute("SELL", state)
            writer.assert_not_called()


class PaperExecutionDemoTests(unittest.TestCase):
    def test_stop_and_freeze_reopen_at_expected_checkpoint(self):
        root = Path(__file__).resolve().parents[1]
        for state, sell, cash, units, sequence in (
            ("STOP", "Paper SELL: 1 unit at 101.00", "10001.00", 0, 2),
            ("FREEZE", "Paper SELL blocked by FREEZE", "9900.00", 1, 1),
        ):
            with self.subTest(state=state):
                result = subprocess.run(
                    [sys.executable, "-m", "ariyan_trading", "--governed",
                     "--execution-state", state],
                    cwd=root, env={**os.environ, "PYTHONPATH": str(root / "app")},
                    capture_output=True, text=True, timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for line in (
                    f"Governed BUY: Paper BUY blocked by {state}", sell,
                    f"Verified cash: {cash}", f"Checkpoint sequence: {sequence}",
                    "Authenticated reopening: PASSED",
                ):
                    self.assertIn(line, result.stdout.splitlines())
                verified_units = next(
                    line.split(":", 1)[1] for line in result.stdout.splitlines()
                    if line.startswith("Verified units:")
                )
                self.assertEqual(Decimal(verified_units), units)
