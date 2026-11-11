import io
import json
import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ariyan_trading import checkpoint_coordinator, paper_pending_diagnostic as diagnostic
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_commitment import entry_commitment
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.paper_active_selection import create_paper_active_selection
from ariyan_trading.paper_entry import PaperExecutionDenied
from ariyan_trading.paper_execution_controller import PaperExecutionController
from ariyan_trading.paper_pending_clearance import (
    ACTION, VERSION, PendingClearanceUncertain, assess_pending_clearance,
    clearance_payload, clear_published_pending_marker,
)
from ariyan_trading.paper_execution_state import create_pinned_paper_execution_state
from ariyan_trading import paper_unpublished_order_review as order_review
from ariyan_trading import paper_unpublished_checkpoint_publication as recovery
from ariyan_trading import trust_anchor
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
        self.assertNotIn("unpublished_order", report)
        with self.assertRaisesRegex(ValueError, "previous verified anchor"):
            self.inspect(include_unpublished_order=True)
        self.assertEqual(before, {path: path.read_bytes() for path in inputs})

    def test_valid_hmac_for_divergent_anchor_is_reported_as_outside_expected_tips(self):
        self.set_pending()
        write_anchor(self.anchor, create_anchor(1, "0" * 64, self.key), self.key)
        report = self.inspect()
        self.assertEqual(report["anchor_position"], "OUTSIDE_EXPECTED_TIPS")
        self.assertFalse(report["repair_authorized"])
        with self.assertRaisesRegex(ValueError, "previous verified anchor"):
            self.inspect(include_unpublished_order=True)

    def set_unpublished(self):
        self.set_pending()
        with closing(sqlite3.connect(self.database)) as db:
            genesis = db.execute(
                "SELECT value FROM ledger_meta WHERE key='journal_genesis'"
            ).fetchone()[0]
        write_anchor(self.anchor, create_anchor(0, genesis, self.key), self.key)

    def test_cli_reviews_unpublished_order_without_changes(self):
        self.set_unpublished()
        inputs = (self.database, self.anchor, self.selector, self.state, self.key_file)
        before = tuple(path.read_bytes() for path in inputs)
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(diagnostic.main([
                "--database", str(self.database), "--anchor", str(self.anchor),
                "--selector", str(self.selector), "--expected-state-sha256", self.pin,
                "--checkpoint-key-file", str(self.key_file), "--include-unpublished-order",
            ]), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["anchor_position"], "AT_PREVIOUS_VERIFIED_TIP")
        self.assertEqual(report["unpublished_order"], {
            "request_id": "seed", "action": "BUY", "quantity": "1.00000000", "price": "10.00",
            "cash_delta": "-10.00", "units_delta": "1.00000000", "authenticated_by_anchor": False,
        })
        self.assertFalse(report["write_authorized"])
        self.assertEqual(before, tuple(path.read_bytes() for path in inputs))

    def unpublished_review_intent(self):
        report = self.inspect(include_unpublished_order=True, include_clearance_binding=True)
        self.assertNotEqual(
            report["clearance_binding_sha256"], report["unpublished_order_review_sha256"],
        )
        return {
            "version": order_review.VERSION, "action": order_review.ACTION,
            "unpublished_order_review_sha256": report["unpublished_order_review_sha256"],
            "expires_at_ms": 100, "request_id": "seed", "side": "BUY",
            "quantity": "1", "price": "10",
        }

    def assess_unpublished_review(self, signer, intent, **overrides):
        options = {
            "signature": signer.sign(order_review.unpublished_order_review_payload(intent)),
            "expected_state_sha256": self.pin, "checkpoint_key": self.key,
            "operator_public_key": signer.public_key().public_bytes_raw(), "as_of_ms": 99,
        }
        options.update(overrides)
        return order_review.assess_unpublished_order_review(
            self.database, self.anchor, self.selector, intent, **options,
        )

    def test_signed_unpublished_review_matches_independent_order_without_changes(self):
        self.set_unpublished()
        intent = self.unpublished_review_intent()
        signer = Ed25519PrivateKey.generate()
        files = (self.database, self.anchor, self.selector, self.state)
        before = tuple(path.read_bytes() for path in files)
        result = self.assess_unpublished_review(signer, intent)
        self.assertEqual(result["status"], "SIGNED_REVIEW_MATCHES_UNPUBLISHED_PAPER_ORDER")
        self.assertFalse(result["write_authorized"])
        self.assertFalse(result["live_authorized"])
        self.assertTrue(result["checkpoint_inspection"]["publication_pending"])
        self.assertEqual(before, tuple(path.read_bytes() for path in files))

    def test_signed_unpublished_review_rejects_wrong_order_signature_and_expiry(self):
        self.set_unpublished()
        intent = self.unpublished_review_intent()
        signer = Ed25519PrivateKey.generate()
        for field, value in (("request_id", "other"), ("side", "SELL"),
                             ("quantity", "2"), ("price", "11")):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "Signed order differs"):
                self.assess_unpublished_review(signer, {**intent, field: value})
        other_key = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        with self.assertRaisesRegex(ValueError, "Invalid operator review signature"):
            self.assess_unpublished_review(signer, intent, operator_public_key=other_key)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.assess_unpublished_review(signer, intent, as_of_ms=100)

    def test_signed_unpublished_review_rejects_changed_marker_or_published_tip(self):
        self.set_unpublished()
        intent = self.unpublished_review_intent()
        signer = Ed25519PrivateKey.generate()
        report = self.inspect()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE ledger_meta SET value=? WHERE key=?",
                       ("b" * 32, checkpoint_coordinator.PENDING))
        with self.assertRaisesRegex(ValueError, "freshly inspected checkpoint"):
            self.assess_unpublished_review(signer, intent)
        write_anchor(self.anchor, create_anchor(1, report["journal_digest"], self.key), self.key)
        with self.assertRaisesRegex(ValueError, "previous verified anchor"):
            self.assess_unpublished_review(signer, intent)

    def test_signed_unpublished_review_rejects_rehashed_wrong_deltas(self):
        self.set_unpublished()
        report = self.inspect()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE ledger_entries SET cash_delta='-1.00' WHERE sequence=1")
            row = db.execute(
                "SELECT sequence,request_id,action,quantity,price,cash_delta,units_delta "
                "FROM ledger_entries WHERE sequence=1"
            ).fetchone()
            db.execute("UPDATE journal_commitments SET digest=? WHERE sequence=1",
                       (entry_commitment(report["anchor_digest"], *row),))
        intent = self.unpublished_review_intent()
        with self.assertRaisesRegex(ValueError, "deltas differ"):
            self.assess_unpublished_review(Ed25519PrivateKey.generate(), intent)

    def publication_intent(self):
        return {
            **self.unpublished_review_intent(),
            "version": recovery.VERSION, "action": recovery.ACTION,
        }

    def publish(self, signer, intent, *, signature=None):
        if signature is None:
            signature = signer.sign(recovery.unpublished_checkpoint_publication_payload(intent))
        return recovery.publish_unpublished_paper_checkpoint(
            self.database, self.anchor, self.selector, intent, signature,
            expected_state_sha256=self.pin, checkpoint_key=self.key,
            operator_public_key=signer.public_key().public_bytes_raw(),
        )

    def test_publication_rejects_review_signature_wrong_order_and_late_expiry(self):
        self.set_unpublished()
        review = self.unpublished_review_intent()
        intent = self.publication_intent()
        signer = Ed25519PrivateKey.generate()
        files = (self.database, self.anchor, self.selector, self.state)
        before = tuple(path.read_bytes() for path in files)
        with patch.object(recovery.time, "time_ns", return_value=99_000_000):
            signature = signer.sign(order_review.unpublished_order_review_payload(review))
            with self.assertRaisesRegex(ValueError, "Unsupported unpublished order review intent"):
                self.publish(signer, review, signature=signature)
            with self.assertRaisesRegex(ValueError, "Invalid operator review signature"):
                self.publish(signer, intent, signature=signature)
            with self.assertRaisesRegex(ValueError, "Signed order differs"):
                self.publish(signer, {**intent, "price": "11"})
        with patch.object(recovery.time, "time_ns", side_effect=[99_000_000, 100_000_000]):
            with self.assertRaisesRegex(ValueError, "expired before the anchor write"):
                self.publish(signer, intent)
        self.assertEqual(before, tuple(path.read_bytes() for path in files))

    def test_publication_rejects_unaffordable_order_with_valid_deltas(self):
        self.set_unpublished()
        report = self.inspect()
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute(
                "UPDATE ledger_entries SET price='1001.00',cash_delta='-1001.00' WHERE sequence=1"
            )
            row = db.execute(
                "SELECT sequence,request_id,action,quantity,price,cash_delta,units_delta "
                "FROM ledger_entries WHERE sequence=1"
            ).fetchone()
            db.execute("UPDATE journal_commitments SET digest=? WHERE sequence=1",
                       (entry_commitment(report["anchor_digest"], *row),))
        intent = {**self.publication_intent(), "price": "1001"}
        anchor_before = self.anchor.read_bytes()
        with patch.object(recovery.time, "time_ns", return_value=99_000_000):
            with self.assertRaisesRegex(ValueError, "Journal overspent cash"):
                self.publish(Ed25519PrivateKey.generate(), intent)
        self.assertEqual(anchor_before, self.anchor.read_bytes())
        self.assertTrue(self.inspect()["publication_pending"])

    def test_publication_requires_inspection_if_anchor_write_result_is_lost(self):
        self.set_unpublished()
        intent = self.publication_intent()
        signer = Ed25519PrivateKey.generate()

        def lose_result(*args):
            write_anchor(*args)
            raise OSError("simulated lost publication result")

        files = (self.database, self.selector, self.state)
        before = tuple(path.read_bytes() for path in files)
        with patch.object(recovery.time, "time_ns", return_value=99_000_000):
            with patch.object(recovery, "write_anchor", side_effect=lose_result):
                with self.assertRaisesRegex(recovery.PaperCheckpointPublicationUncertain, "inspection"):
                    self.publish(signer, intent)
            with self.assertRaisesRegex(ValueError, "previous verified anchor"):
                self.publish(signer, intent)
        report = self.inspect()
        self.assertEqual(report["anchor_position"], "AT_VERIFIED_JOURNAL_TIP")
        self.assertTrue(report["publication_pending"])
        self.assertEqual(before, tuple(path.read_bytes() for path in files))

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

    def test_recovery_status_cli_verifies_clean_tip_read_only(self):
        files = (self.database, self.anchor, self.selector, self.state)
        before = tuple(path.read_bytes() for path in files)
        with redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(diagnostic.main([
                "--database", str(self.database), "--anchor", str(self.anchor),
                "--selector", str(self.selector), "--expected-state-sha256", self.pin,
                "--checkpoint-key-file", str(self.key_file), "--recovery-status",
            ]), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["status"], "NO_PENDING_VERIFIED_TIP")
        self.assertEqual(report["version"], diagnostic.RECOVERY_STATUS_VERSION)
        self.assertEqual(report["journal_sequence"], 1)
        for key in ("publication_pending", "repair_authorized", "write_authorized", "live_authorized"):
            self.assertFalse(report[key])
        self.assertEqual(before, tuple(path.read_bytes() for path in files))

    def test_recovery_status_classifies_pending_tips_and_rejects_missing_marker_at_stale_tip(self):
        self.set_unpublished()
        self.assertEqual(self.inspect(recovery_status=True)["status"], "PENDING_AT_PREVIOUS_TIP")
        report = self.inspect()
        write_anchor(self.anchor, create_anchor(1, report["journal_digest"], self.key), self.key)
        self.assertEqual(self.inspect(recovery_status=True)["status"], "PENDING_AT_PUBLISHED_TIP")
        write_anchor(self.anchor, create_anchor(1, "0" * 64, self.key), self.key)
        self.assertEqual(self.inspect(recovery_status=True)["status"], "PENDING_WITH_DIVERGENT_ANCHOR")
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE ledger_meta SET value='invalid' WHERE key=?", (checkpoint_coordinator.PENDING,))
        with self.assertRaisesRegex(ValueError, "Expected a coordinator pending publication marker"):
            self.inspect(recovery_status=True)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("DELETE FROM ledger_meta WHERE key=?", (checkpoint_coordinator.PENDING,))
        with self.assertRaisesRegex(ValueError, "differs from the journal tip"):
            self.inspect(recovery_status=True)

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

    def apply_clearance(self, signer, intent, *, clock_values=None):
        with patch("ariyan_trading.paper_pending_clearance.time.time_ns",
                   return_value=99_000_000, side_effect=clock_values):
            return clear_published_pending_marker(
                self.database, self.anchor, self.selector, intent,
                signer.sign(clearance_payload(intent)), expected_state_sha256=self.pin,
                checkpoint_key=self.key, operator_public_key=signer.public_key().public_bytes_raw(),
            )

    def test_applied_clearance_removes_only_marker_and_keeps_freeze(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        files = (self.anchor, self.selector, self.state)
        before = {path: path.read_bytes() for path in files}
        with closing(sqlite3.connect(self.database)) as db:
            before_dump = tuple(db.iterdump())

        result = self.apply_clearance(signer, intent)
        self.assertEqual(result["status"], "PUBLISHED_PENDING_MARKER_CLEARED")
        self.assertEqual(result["journal_sequence"], 1)
        self.assertEqual(before, {path: path.read_bytes() for path in files})
        with closing(DurableLedger(
            self.database, checkpoint_path=self.anchor, checkpoint_key=self.key,
        )) as ledger:
            self.assertEqual(tuple(ledger.db.iterdump()), tuple(
                line for line in before_dump if f"'{checkpoint_coordinator.PENDING}'" not in line
            ))
            controller = PaperExecutionController.reopen(
                self.selector, ledger_identity=self.identity, expected_state_sha256=self.pin,
                checkpoint_key=self.key, operator_public_key=signer.public_key().public_bytes_raw(),
            )
            with self.assertRaisesRegex(PaperExecutionDenied, "blocked by FREEZE"):
                controller.execute(ledger, "SELL", "frozen", "1", "10.00", anchor_path=self.anchor)
        with self.assertRaisesRegex(ValueError, "pending publication marker"):
            self.apply_clearance(signer, intent)

    def test_applied_clearance_rolls_back_unexpected_trigger_side_effect(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(
                "CREATE TRIGGER unexpected_meta_change AFTER DELETE ON ledger_meta "
                "BEGIN INSERT INTO ledger_meta(key,value) VALUES ('unexpected','side-effect'); END"
            )
        with self.assertRaisesRegex(ValueError, "change only the inspected marker"):
            self.apply_clearance(signer, intent)
        self.assertTrue(self.inspect()["publication_pending"])
        with closing(sqlite3.connect(self.database)) as db:
            self.assertIsNone(db.execute(
                "SELECT value FROM ledger_meta WHERE key='unexpected'"
            ).fetchone())

    def test_clearance_preserves_marker_on_file_or_directory_sync_failure(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        files = (self.database, self.anchor, self.selector, self.state)
        before = tuple(path.read_bytes() for path in files)
        real_fsync = os.fsync
        for failure in ("file", "directory"):
            with self.subTest(failure=failure):
                attempted = []

                def sync(fd):
                    kind = "directory" if stat.S_ISDIR(os.fstat(fd).st_mode) else "file"
                    attempted.append(kind)
                    if kind == failure:
                        raise OSError("simulated anchor sync failure")
                    real_fsync(fd)

                with patch.object(trust_anchor.os, "fsync", side_effect=sync):
                    with self.assertRaisesRegex(OSError, "simulated anchor sync failure"):
                        self.apply_clearance(signer, intent)
                self.assertEqual(attempted, ["file"] if failure == "file" else ["file", "directory"])
                self.assertEqual(before, tuple(path.read_bytes() for path in files))
                self.assertTrue(self.inspect()["publication_pending"])
        self.assertEqual(
            self.apply_clearance(signer, intent)["status"], "PUBLISHED_PENDING_MARKER_CLEARED",
        )

    def test_clearance_rejects_anchor_replacement_during_sync(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        replacement = self.anchor.with_name("replacement.json")
        replacement.write_bytes(self.anchor.read_bytes())
        real_sync_directory = trust_anchor._sync_directory

        def replace_before_sync(path):
            replacement.replace(self.anchor)
            real_sync_directory(path)

        with patch.object(trust_anchor, "_sync_directory", side_effect=replace_before_sync):
            with self.assertRaisesRegex(ValueError, "Anchor path changed during sync"):
                self.apply_clearance(signer, intent)
        self.assertTrue(self.inspect()["publication_pending"])

    def test_clearance_rejects_intent_that_expires_during_sync(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        with self.assertRaisesRegex(ValueError, "expired during anchor sync"):
            self.apply_clearance(signer, intent, clock_values=[99_000_000, 100_000_000])
        self.assertTrue(self.inspect()["publication_pending"])

    def test_applied_clearance_reports_uncertainty_if_commit_result_is_lost(self):
        self.set_pending()
        signer = Ed25519PrivateKey.generate()
        intent = self.clearance_intent()
        real_connect = sqlite3.connect

        class LostCommitResponse(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                result = super().execute(sql, *args, **kwargs)
                if sql == "COMMIT":
                    raise sqlite3.OperationalError("simulated lost commit response")
                return result

        with patch("ariyan_trading.paper_pending_clearance.sqlite3.connect",
                   side_effect=lambda *args, **kwargs: real_connect(
                       *args, factory=LostCommitResponse, **kwargs,
                   )):
            with self.assertRaisesRegex(PendingClearanceUncertain, "do not retry"):
                self.apply_clearance(signer, intent)
        with self.assertRaisesRegex(ValueError, "pending publication marker"):
            self.inspect()
        self.assertEqual(self.inspect(recovery_status=True)["status"], "NO_PENDING_VERIFIED_TIP")
