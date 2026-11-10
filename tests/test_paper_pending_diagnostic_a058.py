import io
import json
import os
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import checkpoint_coordinator, paper_pending_diagnostic as diagnostic
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.paper_active_selection import create_paper_active_selection
from ariyan_trading.paper_pending_clearance import (
    ACTION, VERSION, assess_pending_clearance, clearance_payload,
)
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading.trust_anchor import create_anchor, write_anchor


@unittest.skipIf(os.name == "nt", "Requires native A006 anchor publication")
class PaperPendingDiagnosticTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        self.database = root / "ledger.sqlite"
        self.anchor = root / "anchor.json"
        self.selector = root / "active.json"
        self.state = root / "freeze.json"
        self.key_file = root / "key.bin"
        self.key = b"disposable-a058-test-key-only!!!"
        self.key_file.write_bytes(self.key)
        with closing(DurableLedger(self.database, opening_cash="1000.00")) as ledger:
            with ledger.db:
                ledger.db.execute("BEGIN")
                digest = verify_protected_journal(ledger.db, ledger.opening_cash)
            write_anchor(self.anchor, create_anchor(0, digest, self.key), self.key)
            checkpoint_coordinator.execute_checkpointed_trade(
                ledger, "BUY", "seed", "1", "10.00", anchor_path=self.anchor, key=self.key,
            )
            self.identity = ledger.ledger_identity
        self.pin = create_pinned_paper_execution_state(
            self.state, self.identity, "FREEZE", key=self.key,
        )
        create_paper_active_selection(
            self.selector, self.state, ledger_identity=self.identity,
            expected_state_sha256=self.pin, checkpoint_key=self.key,
        )

    def set_pending(self):
        with closing(DurableLedger(self.database, opening_cash="1000.00")) as ledger:
            ledger.db.execute(
                "INSERT INTO ledger_meta(key,value) VALUES (?,?)",
                (checkpoint_coordinator.PENDING, "a" * 32),
            )

    def inspect(self, **overrides):
        options = {"expected_state_sha256": self.pin, "key": self.key}
        options.update(overrides)
        return diagnostic.inspect_pending_paper_checkpoint(
            self.database, self.anchor, self.selector, **options,
        )

    def test_cli_classifies_published_anchor_with_pending_marker_without_changes(self):
        self.set_pending()
        inputs = (self.database, self.anchor, self.selector, self.state, self.key_file)
        before = {path: path.read_bytes() for path in inputs}
        args = [
            "--database", str(self.database), "--anchor", str(self.anchor),
            "--selector", str(self.selector), "--expected-state-sha256", self.pin,
            "--checkpoint-key-file", str(self.key_file),
        ]
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(diagnostic.main(args), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["anchor_position"], "AT_VERIFIED_JOURNAL_TIP")
        self.assertTrue(report["publication_pending"])
        self.assertFalse(report["write_authorized"])
        self.assertEqual(before, {path: path.read_bytes() for path in inputs})

    def test_valid_hmac_for_divergent_anchor_is_reported_as_outside_expected_tips(self):
        self.set_pending()
        write_anchor(self.anchor, create_anchor(1, "0" * 64, self.key), self.key)
        report = self.inspect()
        self.assertEqual(report["anchor_position"], "OUTSIDE_EXPECTED_TIPS")
        self.assertFalse(report["repair_authorized"])

    def test_requires_pending_marker_matching_pin_and_freeze(self):
        with self.assertRaisesRegex(ValueError, "pending publication marker"):
            self.inspect()
        self.set_pending()
        with self.assertRaisesRegex(ValueError, "independently retained pin"):
            self.inspect(expected_state_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "authentication"):
            self.inspect(key=b"x" * 32)
        self.selector.unlink()
        stop = self.state.with_name("stop.json")
        stop_pin = create_pinned_paper_execution_state(stop, self.identity, "STOP", key=self.key)
        create_paper_active_selection(
            self.selector, stop, ledger_identity=self.identity,
            expected_state_sha256=stop_pin, checkpoint_key=self.key,
        )
        with self.assertRaisesRegex(ValueError, "requires FREEZE"):
            self.inspect(expected_state_sha256=stop_pin)

    def test_cli_rejects_without_echoing_private_input(self):
        with redirect_stderr(io.StringIO()) as stderr, self.assertRaises(SystemExit) as error:
            diagnostic.main([
                "--database", str(self.database), "--anchor", str(self.anchor),
                "--selector", str(self.selector), "--expected-state-sha256", self.pin,
                "--checkpoint-key-file", str(self.key_file),
            ])
        self.assertEqual(error.exception.code, 2)
        self.assertIn("no repair performed", stderr.getvalue())
        self.assertNotIn(str(self.key_file), stderr.getvalue())

    def clearance_intent(self):
        report = self.inspect(include_clearance_binding=True)
        return {
            "version": VERSION, "action": ACTION,
            "clearance_binding_sha256": report["clearance_binding_sha256"],
            "expires_at_ms": 100,
        }

    def assess_clearance(self, signer, intent, **overrides):
        options = {
            "signature": signer.sign(clearance_payload(intent)),
            "expected_state_sha256": self.pin, "checkpoint_key": self.key,
            "operator_public_key": signer.public_key().public_bytes_raw(), "as_of_ms": 99,
        }
        options.update(overrides)
        return assess_pending_clearance(self.database, self.anchor, self.selector, intent, **options)

    def test_clearance_matches_published_tip_and_preserves_the_pending_marker(self):
        self.set_pending()
        self.assertNotIn("clearance_binding_sha256", self.inspect())
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        inputs = (self.database, self.anchor, self.selector, self.state)
        before = {path: path.read_bytes() for path in inputs}
        result = self.assess_clearance(signer, intent)
        self.assertEqual(result["status"], "SIGNED_APPROVAL_MATCHES_INSPECTED_PENDING_CHECKPOINT")
        self.assertFalse(result["write_authorized"])
        self.assertTrue(result["checkpoint_inspection"]["publication_pending"])
        self.assertEqual(before, {path: path.read_bytes() for path in inputs})

    def test_clearance_rejects_changed_marker_wrong_signer_and_expiry(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        other = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        with self.assertRaisesRegex(ValueError, "Invalid operator"):
            self.assess_clearance(signer, intent, operator_public_key=other)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.assess_clearance(signer, intent, as_of_ms=100)
        with closing(DurableLedger(self.database, opening_cash="1000.00")) as ledger:
            ledger.db.execute("UPDATE ledger_meta SET value=? WHERE key=?",
                              ("b" * 32, checkpoint_coordinator.PENDING))
        with self.assertRaisesRegex(ValueError, "freshly inspected"):
            self.assess_clearance(signer, intent)

    def test_signed_clearance_does_not_accept_previous_anchor_tip(self):
        self.set_pending()
        with closing(DurableLedger(self.database, opening_cash="1000.00")) as ledger:
            genesis = ledger.db.execute(
                "SELECT value FROM ledger_meta WHERE key='journal_genesis'"
            ).fetchone()[0]
        write_anchor(self.anchor, create_anchor(0, genesis, self.key), self.key)
        self.assertEqual(self.inspect()["anchor_position"], "AT_PREVIOUS_VERIFIED_TIP")
        intent = self.clearance_intent()
        with self.assertRaisesRegex(ValueError, "current journal tip"):
            self.assess_clearance(Ed25519PrivateKey.generate(), intent)
