import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ariyan_trading.predictability_gate import assess_new_exposure
from ariyan_trading.validation_evaluation import evaluate_plan
from ariyan_trading.validation_plan import freeze_plan
from test_validation_plan_a036 import HOUR, specification

FIXTURE = Path("examples/a007/BTCUSDT-1h-2024-01-01.csv")
FIXTURE_START = 1_704_067_200_000


class ValidationEvaluationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.csv = self.root / "candles.csv"
        self.spec = specification()
        self.spec["market"].update(input_format="canonical", source="synthetic test")
        self.spec["criteria"]["max_close_drawdown_pct"] = "100"
        self.start = self.spec["window"]["start_ms"]
        self.end = self.spec["window"]["end_ms"]
        self.rows = ["timestamp_ms,open,high,low,close,volume"] + [
            f"{self.start + index * HOUR},{price},{price},{price},{price},10"
            for index, price in enumerate(range(100, 148, 2))
        ]
        self.write_candles(self.rows)

    def write_candles(self, rows):
        self.csv.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def test_exact_input_and_plan_binding_with_both_scenarios_passing(self):
        plan = freeze_plan(self.spec, created_at_ms=0)
        report = evaluate_plan(plan, self.csv, as_of_ms=self.end)
        self.assertTrue(report["criteria_met"])
        self.assertEqual(report["plan_sha256"], plan["plan_sha256"])
        self.assertEqual(report["declared_code_commit"], self.spec["code_commit"])
        self.assertFalse(report["code_commit_verified"])
        self.assertFalse(report["plan_publication_time_verified"])
        self.assertFalse(report["prospective_validation_established"])
        self.assertFalse(report["live_authorized"])
        self.assertEqual(assess_new_exposure()["decision"], "NO_TRADE")

        dataset = report["evaluation"]["dataset"]
        self.assertEqual(dataset["raw_sha256"], hashlib.sha256(self.csv.read_bytes()).hexdigest())
        self.assertEqual(dataset["as_of_ms"], self.end)
        self.assertEqual(dataset["candles"], 24)
        self.assertEqual(evaluate_plan(plan, self.csv, as_of_ms=self.end + HOUR), report)

    def test_a_failed_stress_scenario_blocks_combined_pass(self):
        self.spec["stress_costs"] = {"fee_bps": "1000", "slippage_bps": "1000"}
        plan = freeze_plan(self.spec, created_at_ms=0)
        report = evaluate_plan(plan, self.csv, as_of_ms=self.end)
        self.assertTrue(report["checks"]["base"]["criteria_met"])
        self.assertFalse(report["checks"]["stress"]["min_positive_periods_met"])
        self.assertFalse(report["criteria_met"])

    def test_per_period_order_and_drawdown_limits_are_enforced(self):
        self.spec["criteria"]["max_close_drawdown_pct"] = "0"
        self.spec["criteria"]["min_filled_orders_per_period"] = 3
        plan = freeze_plan(self.spec, created_at_ms=0)
        report = evaluate_plan(plan, self.csv, as_of_ms=self.end)
        periods = report["checks"]["stress"]["periods"]
        self.assertTrue(any(not row["max_close_drawdown_met"] for row in periods))

        flat_rows = [self.rows[0]] + [
            f"{self.start + index * HOUR},100,100,100,100,10"
            for index in range(24)
        ]
        self.write_candles(flat_rows)
        report = evaluate_plan(plan, self.csv, as_of_ms=self.end)
        self.assertTrue(all(
            not row["min_filled_orders_met"] for row in report["checks"]["base"]["periods"]
        ))
        self.assertFalse(report["criteria_met"])

    def test_rejects_open_window_modified_plan_and_inexact_candle_coverage(self):
        plan = freeze_plan(self.spec, created_at_ms=0)
        with self.assertRaisesRegex(ValueError, "still open"):
            evaluate_plan(plan, self.root / "does-not-exist", as_of_ms=self.end - 1)
        modified = {**plan, "plan_sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            evaluate_plan(modified, self.csv, as_of_ms=self.end)

        for rows in (
            [self.rows[0], *self.rows[2:]],
            self.rows[:-1],
            [*self.rows[:10], *self.rows[11:]],
            [*self.rows, f"{self.end},150,150,150,150,10"],
        ):
            with self.subTest(rows=len(rows)):
                self.write_candles(rows)
                with self.assertRaises(ValueError):
                    evaluate_plan(plan, self.csv, as_of_ms=self.end)

    def test_cli_runs_real_data_smoke_and_preserves_existing_report(self):
        spec = specification(FIXTURE_START)
        plan = freeze_plan(spec, created_at_ms=0)
        plan_path = self.root / "plan.json"
        output = self.root / "report.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        command = [
            sys.executable, "-m", "ariyan_trading.validation_evaluation",
            "--plan", plan_path, "--csv", FIXTURE, "--output", output,
        ]
        run = subprocess.run(command, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        saved = output.read_bytes()
        report = json.loads(saved)
        self.assertEqual(report["plan_sha256"], plan["plan_sha256"])
        self.assertEqual(report["evaluation"]["dataset"]["candles"], 24)
        expected = b"CRITERIA_MET" if report["criteria_met"] else b"CRITERIA_NOT_MET"
        self.assertEqual(run.stdout.strip(), expected)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)
        self.assertEqual(output.read_bytes(), saved)
