"""Integration coverage for the governed paper demo command."""

from decimal import Decimal
import os
from pathlib import Path
import subprocess
import sys
import unittest


class GovernedDemoA029Tests(unittest.TestCase):
    def test_governed_demo_denies_new_exposure_and_verifies_exit(self):
        project = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, '-m', 'ariyan_trading', '--governed'],
            cwd=project, env={**os.environ, 'PYTHONPATH': str(project / 'app')},
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for line in (
            'ARIYAN TRADING AI — A029',
            'Synthetic starting position: 1 unit at 100.00',
            'Governed BUY: NO_TRADE MISSING_VALIDATION_EVIDENCE',
            'Paper SELL: 1 unit at 101.00',
            'Verified cash: 10001.00',
            'Checkpoint sequence: 2',
            'Authenticated reopening: PASSED',
        ):
            self.assertIn(line, result.stdout.splitlines())
        units = next(
            line.split(':', 1)[1]
            for line in result.stdout.splitlines() if line.startswith('Verified units:')
        )
        self.assertEqual(Decimal(units), 0)
