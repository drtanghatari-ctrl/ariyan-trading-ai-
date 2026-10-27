"""A006 executable demo integration through a fresh Python process."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class CheckpointDemoA006Tests(unittest.TestCase):
    def test_module_demo_executes_and_reopens_decimal_ledger(self):
        project = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(project / "app")
        result = subprocess.run(
            [sys.executable, "-m", "ariyan_trading"],
            cwd=project, env=env,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(
            result.returncode, 0, result.stdout + result.stderr
        )
        self.assertIn("Verified cash: 10001.00", result.stdout)
        self.assertIn("Verified units: 0", result.stdout)
        self.assertIn("Checkpoint sequence: 2", result.stdout)
        self.assertIn("Authenticated reopening: PASSED", result.stdout)
        self.assertIn("SYNTHETIC PRICES", result.stdout)
        self.assertIn("NO LIVE FINANCIAL ACTIONS", result.stdout)


if __name__ == "__main__":
    unittest.main()
