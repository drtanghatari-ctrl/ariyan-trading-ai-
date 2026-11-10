import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ariyan_trading import paper_entry
from ariyan_trading.ledger_identity import new_ledger_identity
from ariyan_trading.paper_execution_state import (
    create_paper_execution_state, read_paper_execution_state,
)


class PaperStatePinTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.state = self.root / "state.json"
        self.key = b"disposable-a051-test-key-only!!!"
        self.ledger = SimpleNamespace(ledger_identity=new_ledger_identity())

    def create(self, path, state, *, key=None):
        create_paper_execution_state(
            path, self.ledger.ledger_identity, state, key=self.key if key is None else key,
        )
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def sell(self, pin, *, path=True):
        return paper_entry.execute_governed_paper_trade(
            self.ledger, "SELL", "order", "1", "10.00",
            anchor_path=self.root / "anchor.json", key=self.key,
            execution_state_path=self.state if path else None,
            expected_execution_state_sha256=pin,
        )

    def test_restored_valid_normal_record_cannot_override_pinned_freeze(self):
        old_state = self.root / "older.json"
        self.create(old_state, "NORMAL")
        freeze_pin = self.create(self.state, "FREEZE")
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaisesRegex(paper_entry.PaperExecutionDenied, "blocked by FREEZE"):
                self.sell(freeze_pin)
            self.state.write_bytes(old_state.read_bytes())
            self.assertEqual(read_paper_execution_state(
                self.state, self.ledger.ledger_identity, key=self.key,
            ), "NORMAL")
            with self.assertRaisesRegex(ValueError, "differs from the expected SHA-256"):
                self.sell(freeze_pin)
            writer.assert_not_called()

    def test_matching_pin_preserves_stop_and_still_requires_authentication(self):
        pin = self.create(self.state, "STOP")
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            self.assertIs(self.sell(pin), writer.return_value)
            writer.assert_called_once()
            writer.reset_mock()
            self.state.unlink()
            wrong_key_pin = self.create(self.state, "STOP", key=b"x" * 32)
            with self.assertRaisesRegex(ValueError, "authentication"):
                self.sell(wrong_key_pin)
            writer.assert_not_called()

    def test_pin_cannot_be_used_without_file_or_with_invalid_encoding(self):
        self.create(self.state, "NORMAL")
        with patch.object(paper_entry, "execute_checkpointed_trade") as writer:
            with self.assertRaisesRegex(ValueError, "requires a paper execution state file"):
                self.sell("a" * 64, path=False)
            for pin in ("A" * 64, "", b"a" * 64):
                with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, "lowercase hex"):
                    self.sell(pin)
            writer.assert_not_called()
