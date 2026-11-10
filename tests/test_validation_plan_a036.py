import json
import subprocess
import sys
import tempfile
import time
import unittest
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from ariyan_trading.predictability_gate import assess_new_exposure
from ariyan_trading.replay import ReplayConfig
from ariyan_trading.validation_plan import freeze_plan, verify_plan

HOUR = 3_600_000


def specification(start=24 * HOUR):
    return {
        "code_commit": "a" * 40,
        "market": {
            "symbol": "BTCUSDT", "source": "Binance public spot klines",
            "interval_ms": HOUR, "input_format": "binance-spot", "timestamp_unit": "ms",
        },
        "window": {"start_ms": start, "end_ms": start + 24 * HOUR},
        "config": asdict(ReplayConfig()),
        "stress_costs": {"fee_bps": "20", "slippage_bps": "10"},
        "periods": 3,
        "criteria": {
            "min_positive_periods": 2,
            "min_filled_orders_per_period": 1,
            "max_close_drawdown_pct": "5",
        },
    }


class ValidationPlanTests(unittest.TestCase):
    def test_deterministic_round_trip_and_gate_stays_closed(self):
        spec = specification()
        plan = freeze_plan(spec, created_at_ms=0)
        reordered = dict(reversed(list(spec.items())))
        self.assertEqual(freeze_plan(reordered, created_at_ms=0), plan)
        self.assertEqual(verify_plan(json.loads(json.dumps(plan))), plan)
        spec["market"]["symbol"] = "ETHUSDT"
        self.assertEqual(plan["spec"]["market"]["symbol"], "BTCUSDT")
        self.assertEqual(assess_new_exposure()["decision"], "NO_TRADE")

    def test_each_contract_area_is_bound_by_the_digest(self):
        plan = freeze_plan(specification(), created_at_ms=0)
        changes = [
            (None, "code_commit", "b" * 40),
            ("market", "symbol", "ETHUSDT"),
            ("window", "end_ms", 49 * HOUR),
            ("config", "short_window", 2),
            ("stress_costs", "fee_bps", "21"),
            (None, "periods", 2),
            ("criteria", "min_positive_periods", 1),
        ]
        for section, field, value in changes:
            with self.subTest(field=field):
                tampered = deepcopy(plan)
                record = tampered["spec"] if section is None else tampered["spec"][section]
                record[field] = value
                with self.assertRaisesRegex(ValueError, "fingerprint"):
                    verify_plan(tampered)
                updated = freeze_plan(tampered["spec"], created_at_ms=0)
                self.assertNotEqual(updated["plan_sha256"], plan["plan_sha256"])

    def test_rejects_invalid_specifications(self):
        cases = [
            ("window", "start_ms", 0),
            ("window", "end_ms", 49 * HOUR + 1),
            ("window", "end_ms", 25 * HOUR),
            ("market", "timestamp_unit", "seconds"),
            ("config", "opening_cash", 10000),
            ("config", "long_window", 2),
            ("stress_costs", "slippage_bps", "4"),
            ("criteria", "min_positive_periods", True),
            ("criteria", "min_filled_orders_per_period", 4),
            ("criteria", "max_close_drawdown_pct", "101"),
            ("criteria", "unknown_field", "1"),
        ]
        for section, field, value in cases:
            with self.subTest(section=section, field=field, value=value):
                spec = specification()
                spec[section][field] = value
                with self.assertRaises(ValueError):
                    freeze_plan(spec, created_at_ms=0)

    def test_cli_round_trip_and_rejects_overwrite_or_duplicate_keys(self):
        start = (time.time_ns() // 1_000_000 // HOUR + 24) * HOUR
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "spec.json"
            plan = Path(directory) / "plan.json"
            spec.write_text(json.dumps(specification(start)), encoding="utf-8")
            command = [sys.executable, "-m", "ariyan_trading.validation_plan"]

            freeze = subprocess.run([*command, "freeze", spec, plan], capture_output=True)
            self.assertEqual(freeze.returncode, 0, freeze.stderr)
            saved = plan.read_bytes()
            verify = subprocess.run([*command, "verify", plan], capture_output=True)
            self.assertEqual(verify.returncode, 0, verify.stderr)
            self.assertEqual(freeze.stdout, verify.stdout)

            overwrite = subprocess.run([*command, "freeze", spec, plan], capture_output=True)
            self.assertEqual(overwrite.returncode, 2)
            self.assertEqual(plan.read_bytes(), saved)

            spec.write_text('{"periods": 3, "periods": 4}', encoding="utf-8")
            other_plan = plan.with_name("other.json")
            invalid = subprocess.run([*command, "freeze", spec, other_plan], capture_output=True)
            self.assertEqual(invalid.returncode, 2)
            self.assertIn(b"Duplicate JSON key", invalid.stderr)
            self.assertFalse(other_plan.exists())
