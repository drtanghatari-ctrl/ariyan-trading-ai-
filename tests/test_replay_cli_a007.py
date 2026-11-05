"""Fresh-process CLI checks: valid report, rejection, and no overwrite."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReplayCliA007Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.csv = self.root / "data.csv"
        self.csv.write_text(
            "timestamp_ms,open,high,low,close,volume\n"
            + "".join(f"{i*60000},{100+i},{100+i},{100+i},{100+i},10\n" for i in range(10))
        )
        self.output = self.root / "report.json"
        self.env = os.environ.copy()
        self.env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "app")

    def run_cli(self, *extra):
        return subprocess.run(
            [sys.executable, "-m", "ariyan_trading.replay",
             "--csv", str(self.csv), "--symbol", "SYNTHETIC",
             "--interval-ms", "60000", "--source", "synthetic CLI fixture",
             "--as-of-ms", "600000", "--output", str(self.output), *extra],
            env=self.env, capture_output=True, text=True, timeout=15,
        )

    def test_report_and_reproducibility(self):
        original = self.csv.read_bytes()
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("NO LIVE FINANCIAL ACTIONS", result.stdout)
        report = self.output.read_bytes()
        data = json.loads(report)
        self.assertEqual(data["dataset"]["raw_sha256"], hashlib.sha256(original).hexdigest())
        self.assertFalse(data["dataset"]["source_independently_authenticated"])
        self.assertEqual(len(data["equity_curve"]), 10)
        self.output.unlink()
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), report)
        self.assertEqual(self.csv.read_bytes(), original)

    def test_existing_report_and_input_are_not_overwritten(self):
        self.output.write_text("keep this")
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.output.read_text(), "keep this")
        original = self.csv.read_bytes()
        result = self.run_cli("--output", str(self.csv))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.csv.read_bytes(), original)

    def test_invalid_input_config_and_missing_file_create_no_report(self):
        for extra in [("--as-of-ms", "1"), ("--fee-bps", "-1"),
                      ("--timestamp-unit", "us"), ("--long-window", "100")]:
            with self.subTest(extra=extra):
                result = self.run_cli(*extra)
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.output.exists())
                self.assertNotIn("Traceback", result.stderr)
        self.csv.unlink()
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
