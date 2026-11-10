import contextlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from decimal import localcontext, Inexact
from pathlib import Path
from unittest.mock import patch

from symlink_fixture import symlink_or_skip

from ariyan_trading import checkpoint_diagnostic as diagnostic
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class CheckpointDiagnosticA020Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.database = self.root / "ledger.sqlite"
        self.anchor = self.root / "anchor.json"
        self.key_file = self.root / "key.bin"
        self.key = b"A020-disposable-key-never-for-real-use!!"
        self.key_file.write_bytes(self.key)
        ledger = DurableLedger(self.database, opening_cash="1000.00")
        try:
            ledger.db.execute("BEGIN")
            digest = verify_protected_journal(ledger.db, ledger.opening_cash)
            ledger.db.execute("ROLLBACK")
        finally:
            ledger.close()
        write_anchor(self.anchor, create_anchor(0, digest, self.key), self.key)

    def inspect(self, **changes):
        arguments = dict(database=self.database, opening_cash="1000.00",
                         checkpoint=self.anchor, key=self.key)
        arguments.update(changes)
        return diagnostic.inspect_checkpoint(**arguments)

    def metadata(self, key, value):
        with contextlib.closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT OR REPLACE INTO ledger_meta(key,value) VALUES (?,?)", (key, value))

    def command(self):
        return ["--database", str(self.database), "--opening-cash", "1000.00",
                "--checkpoint", str(self.anchor), "--checkpoint-key-file", str(self.key_file)]

    def test_matching_external_checkpoint_does_not_establish_legacy_boundary(self):
        report = self.inspect()
        self.assertEqual(report["boundary"], "LEGACY_DIRECT_WRITE_BOUNDARY_NOT_ESTABLISHED")
        self.assertEqual(report["sequence"], 0)
        self.assertTrue(report["checkpoint_matches_supplied_key_and_journal"])
        # Disposable paper ledger: reproduce the limitation without removing its xfail.
        ledger = DurableLedger(self.database, opening_cash="1000.00")
        try:
            ledger.record_buy("legacy-boundary-proof", "1", "10")
        finally:
            ledger.close()

    def test_managed_marker_describes_guard_without_authenticating_enrollment(self):
        self.metadata("checkpoint_writer_mode", "managed-v1")
        report = self.inspect()
        self.assertEqual(report["boundary"], "LOCAL_MANAGED_MARKER_PRESENT")
        ledger = DurableLedger(self.database, opening_cash="1000.00")
        try:
            with self.assertRaises(RuntimeError):
                ledger.record_buy("blocked", "1", "10")
        finally:
            ledger.close()
        self.assertFalse(report["writer_enrollment_authenticated"])

    def test_local_mode_changes_without_journal_change(self):
        before = self.inspect()
        self.metadata("checkpoint_writer_mode", "managed-v1")
        after = self.inspect()
        self.assertEqual(before["journal_digest"], after["journal_digest"])
        self.assertNotEqual(before["boundary"], after["boundary"])
        self.assertFalse(after["mode_marker_authenticated"])

    def test_unknown_and_empty_modes_fail_closed(self):
        for mode in ("", "managed-v2", "legacy"):
            self.metadata("checkpoint_writer_mode", mode)
            report = self.inspect()
            self.assertEqual(report["local_writer_mode"], mode)
            self.assertEqual(report["boundary"], "UNKNOWN_MODE_DIRECT_WRITES_FAIL_CLOSED")

    def test_pending_publication_always_rejected(self):
        for value in ("pending", ""):
            self.metadata("checkpoint_publication_pending", value)
            with self.assertRaisesRegex(ValueError, "pending|uncertain"):
                self.inspect()

    def test_wrong_key_and_opening_cash_rejected(self):
        for change in ({"key": b"x" * 32}, {"opening_cash": "999.00"}):
            with self.assertRaises(ValueError):
                self.inspect(**change)

    def test_key_types_and_sizes_rejected(self):
        for key in (None, "x" * 32, bytearray(32), b"x" * 31, b"x" * 4097):
            with self.assertRaises(ValueError):
                self.inspect(key=key)

    def test_stale_checkpoint_rejected(self):
        ledger = DurableLedger(self.database, opening_cash="1000.00")
        try:
            ledger.record_buy("advance", "1", "10")
        finally:
            ledger.close()
        with self.assertRaisesRegex(ValueError, "sequence"):
            self.inspect()

    def test_no_authority_or_independent_rollback_claim(self):
        report = self.inspect()
        for name in ("key_authority_established", "writer_enrollment_authenticated",
                     "mode_marker_authenticated", "ledger_identity_authenticated_by_checkpoint",
                     "independent_rollback_resistance_established", "write_authorized", "live_authorized"):
            self.assertIs(report[name], False)
        self.assertNotIn(self.key.decode(), json.dumps(report))

    def test_readonly_connection_and_input_preservation(self):
        before = {p: p.read_bytes() for p in (self.database, self.anchor, self.key_file)}
        original = diagnostic.verify_checkpoint
        def verify(db, *args):
            with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                db.execute("UPDATE ledger_meta SET value=value WHERE key='opening_cash'")
            return original(db, *args)
        with patch.object(diagnostic, "verify_checkpoint", side_effect=verify):
            self.inspect()
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_connection_closed_on_success_and_postopen_failure(self):
        connections = []
        original = diagnostic.DurableLedger
        def opened(*args, **kwargs):
            ledger = original(*args, **kwargs)
            connections.append(ledger.db)
            return ledger
        with patch.object(diagnostic, "DurableLedger", side_effect=opened):
            self.inspect()
            with patch.object(diagnostic, "read_ledger_identity", side_effect=ValueError("fixture")):
                with self.assertRaises(ValueError):
                    self.inspect()
        for db in connections:
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute("SELECT 1")

    def test_missing_files_symlinks_and_aliases_rejected(self):
        for path in (self.root / "missing", self.root):
            with self.assertRaises((ValueError, OSError)):
                self.inspect(database=path)
        with self.subTest(symlink='ledger database'):
            alias = self.root / "alias"
            symlink_or_skip(alias, self.database)
            with self.assertRaises(ValueError):
                self.inspect(database=alias)
        hardlink = self.root / "hardlink"
        if hasattr(os, "link"):
            os.link(self.database, hardlink)
        else:
            # Some Termux Python builds omit os.link; still check same-file rejection.
            hardlink = self.database
        with self.assertRaises(ValueError):
            self.inspect(checkpoint=hardlink)

    def test_hostile_decimal_context_does_not_change_report(self):
        expected = self.inspect()
        with localcontext() as ctx:
            ctx.prec = 2
            ctx.traps[Inexact] = True
            self.assertEqual(self.inspect(), expected)

    def test_cli_json_determinism_and_no_key_echo(self):
        outputs = []
        for _ in range(2):
            result = subprocess.run([sys.executable, "-m", "ariyan_trading.checkpoint_diagnostic",
                                     *self.command()], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
            self.assertEqual(json.loads(result.stdout), self.inspect())
            self.assertNotIn(self.key.decode(), result.stdout + result.stderr)
        self.assertEqual(*outputs)

    def test_cli_rejection_has_no_report_or_secret(self):
        self.key_file.write_bytes(b"x" * 31)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with self.assertRaises(SystemExit) as raised:
                diagnostic.main(self.command())
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn("x" * 31, err.getvalue())

    def test_key_input_alias_rejected(self):
        arguments = self.command()
        arguments[-1] = str(self.anchor)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            diagnostic.main(arguments)

    def test_tip_advance_between_initial_verification_and_inspection_rejected(self):
        original = diagnostic.DurableLedger
        def opened(*args, **kwargs):
            reader = original(*args, **kwargs)
            writer = original(self.database, opening_cash="1000.00")
            try:
                writer.record_buy("concurrent-advance", "1", "10")
            finally:
                writer.close()
            return reader
        with patch.object(diagnostic, "DurableLedger", side_effect=opened):
            with self.assertRaises(ValueError):
                self.inspect()

    def test_missing_or_corrupt_anchor_never_creates_success_report(self):
        self.anchor.unlink()
        with self.assertRaises(OSError):
            self.inspect()
        self.assertFalse(self.anchor.exists())
        self.anchor.write_text("not json")
        with self.assertRaises(ValueError):
            self.inspect()


if __name__ == "__main__":
    unittest.main()
