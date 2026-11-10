import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import paper_entry
from ariyan_trading.checkpoint_coordinator import execute_checkpointed_trade
from ariyan_trading.checkpoint_publication import PublicationState
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.ledger_identity import new_ledger_identity
from ariyan_trading.paper_execution_state import create_paper_execution_state
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class PaperPersistentStateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.state = root / "paper-state.json"
        self.key = b"disposable-a050-test-key-only!!!"
        with closing(self.open_ledger()) as ledger:
            with ledger.db:
                ledger.db.execute("BEGIN")
                digest = verify_protected_journal(ledger.db, ledger.opening_cash)
            write_anchor(self.anchor, create_anchor(0, digest, self.key), self.key)
            execute_checkpointed_trade(
                ledger, "BUY", "seed", "2", "10.00", anchor_path=self.anchor, key=self.key,
            )
            self.identity = ledger.ledger_identity

    def open_ledger(self):
        return DurableLedger(self.database, opening_cash="1000.00")

    def create_state(self, state, *, identity=None, key=None):
        create_paper_execution_state(
            self.state, self.identity if identity is None else identity, state,
            key=self.key if key is None else key,
        )

    def sell(self, ledger, **kwargs):
        return paper_entry.execute_governed_paper_trade(
            ledger, "SELL", "exit", "1", "10.00", anchor_path=self.anchor,
            key=self.key, execution_state_path=self.state, **kwargs,
        )

    def test_freeze_survives_reopen_and_leaves_ledger_and_anchor_unchanged(self):
        self.create_state("FREEZE")
        with closing(self.open_ledger()) as ledger:
            before = tuple(ledger.db.iterdump()), self.anchor.read_bytes()
            statements = []
            ledger.db.set_trace_callback(statements.append)
            try:
                with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                    self.sell(ledger)
            finally:
                ledger.db.set_trace_callback(None)
            self.assertEqual(statements, [])
            self.assertEqual((tuple(ledger.db.iterdump()), self.anchor.read_bytes()), before)

    def test_missing_tampered_wrong_key_and_cross_ledger_state_fail_closed(self):
        with closing(self.open_ledger()) as ledger, \
                patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaises(FileNotFoundError):
                self.sell(ledger)
            self.create_state("FREEZE")
            signed = self.state.read_bytes()
            self.state.write_bytes(signed.replace(b'"FREEZE"', b'"NORMAL"'))
            with self.assertRaisesRegex(ValueError, "authentication"):
                self.sell(ledger)
            self.state.unlink()
            self.create_state("NORMAL", key=b"x" * 32)
            with self.assertRaisesRegex(ValueError, "authentication"):
                self.sell(ledger)
            self.state.unlink()
            self.create_state("NORMAL", identity=new_ledger_identity())
            with self.assertRaisesRegex(ValueError, "ledger identity mismatch"):
                self.sell(ledger)
            writer.assert_not_called()

    def test_stop_allows_checkpointed_exit_and_creation_never_overwrites(self):
        self.create_state("STOP")
        before = self.state.read_bytes()
        with self.assertRaises(FileExistsError):
            self.create_state("NORMAL")
        self.assertEqual(self.state.read_bytes(), before)
        with closing(self.open_ledger()) as ledger:
            with self.assertRaisesRegex(ValueError, "Cannot combine"):
                self.sell(ledger, execution_state="STOP")
            result = self.sell(ledger)
            self.assertIs(result["state"], PublicationState.DURABLE)
            self.assertEqual(result["sequence"], 2)
