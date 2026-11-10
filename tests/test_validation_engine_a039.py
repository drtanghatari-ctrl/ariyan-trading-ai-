import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ariyan_trading import validation_engine
from ariyan_trading.validation_engine import ENGINE_PATHS, verify_engine_sources


@unittest.skipUnless(shutil.which("git"), "Git is required for the source check")
class ValidationEngineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.git("init", "--quiet", "--object-format=sha1")
        self.git("config", "core.autocrlf", "false")
        self.git("config", "core.hooksPath", str(self.root / "disabled-hooks"))
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "user.email", "atai-test@example.invalid")
        self.git("config", "user.name", "ATAI Test")
        source_root = Path(validation_engine.__file__).resolve().parents[2]
        for name in ENGINE_PATHS:
            destination = self.root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_root / name, destination)
        self.git("add", "--", *ENGINE_PATHS)
        self.git("commit", "--quiet", "-m", "Replay engine")
        self.commit = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    def test_old_revision_matches_despite_unrelated_checkout_changes(self):
        (self.root / "unrelated.txt").write_bytes(b"new checkpoint")
        self.git("add", "--", "unrelated.txt")
        self.git("commit", "--quiet", "-m", "Unrelated change")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), self.commit)
        self.assertEqual(verify_engine_sources(self.root, self.commit), ENGINE_PATHS)

    def test_modified_dependency_is_rejected_even_when_index_matches(self):
        dependency = self.root / "app/ariyan_trading/ledger_validation.py"
        with dependency.open("ab") as stream:
            stream.write(b"\n# local edit\n")
        with self.assertRaisesRegex(ValueError, "differs.*ledger_validation.py"):
            verify_engine_sources(self.root, self.commit)

    def test_rejects_missing_object_wrong_object_type_and_missing_committed_source(self):
        with self.assertRaisesRegex(ValueError, "Local Git command failed"):
            verify_engine_sources(self.root, "0" * 40)
        blob = self.git("rev-parse", "HEAD:app/ariyan_trading/replay.py")
        with self.assertRaisesRegex(ValueError, "is not a commit"):
            verify_engine_sources(self.root, blob)
        self.git("rm", "--quiet", "app/ariyan_trading/replay.py")
        self.git("commit", "--quiet", "-m", "Missing replay")
        with self.assertRaisesRegex(ValueError, "lacks a regular source file"):
            verify_engine_sources(self.root, self.git("rev-parse", "HEAD"))

    def test_missing_working_source_is_rejected(self):
        (self.root / "app/ariyan_trading/replay.py").unlink()
        with self.assertRaisesRegex(ValueError, "Checkout lacks.*replay.py"):
            verify_engine_sources(self.root, self.commit)
