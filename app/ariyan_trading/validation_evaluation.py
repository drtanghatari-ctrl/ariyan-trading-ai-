"""Evaluate the exact candle window in a frozen A036 plan offline."""

import argparse
import csv
import json
import time
from decimal import Decimal
from pathlib import Path

from .evaluation import evaluate_periods
from .market_data import integer, load_candles
from .replay import ReplayConfig
from .validation_plan import load_plan, verify_plan

VERSION = "ARIYAN-A037-VALIDATION-EVALUATION-V1"


def _check_scenario(evaluation, scenario, criteria):
    periods = []
    for period in evaluation["periods"]:
        summary = period["scenarios"][scenario]["summary"]
        periods.append({
            "period": period["period"],
            "min_filled_orders_met": (
                summary["filled_orders"] >= criteria["min_filled_orders_per_period"]
            ),
            "max_close_drawdown_met": (
                Decimal(summary["max_close_drawdown_pct"])
                <= Decimal(criteria["max_close_drawdown_pct"])
            ),
        })
    positive_periods_met = (
        evaluation["period_counts"][scenario]["positive_periods"]
        >= criteria["min_positive_periods"]
    )
    return {
        "min_positive_periods_met": positive_periods_met,
        "periods": periods,
        "criteria_met": positive_periods_met and all(
            period["min_filled_orders_met"] and period["max_close_drawdown_met"]
            for period in periods
        ),
    }


def evaluate_plan(plan, csv_path, *, as_of_ms):
    """Run A008 from candle bytes and grade both scenarios against the plan."""
    plan = verify_plan(plan)
    spec = plan["spec"]
    start = spec["window"]["start_ms"]
    end = spec["window"]["end_ms"]
    if integer(as_of_ms, "as_of_ms") < end:
        raise ValueError("Evaluation window is still open")
    dataset = load_candles(csv_path, as_of_ms=end, **spec["market"])
    first_open = dataset.candles[0].timestamp_ms
    last_close = dataset.candles[-1].timestamp_ms + dataset.interval_ms
    if first_open != start or last_close != end:
        raise ValueError("CSV must cover exactly the frozen evaluation window")

    stress = spec["stress_costs"]
    evaluation = evaluate_periods(
        dataset, ReplayConfig(**spec["config"]), periods=spec["periods"],
        stress_fee_bps=stress["fee_bps"], stress_slippage_bps=stress["slippage_bps"],
    )
    checks = {
        scenario: _check_scenario(evaluation, scenario, spec["criteria"])
        for scenario in ("base", "stress")
    }
    return {
        "version": VERSION,
        "plan_sha256": plan["plan_sha256"],
        "declared_code_commit": spec["code_commit"],
        "code_commit_verified": False,
        "plan_publication_time_verified": False,
        "prospective_validation_established": False,
        "live_authorized": False,
        "criteria": spec["criteria"],
        "criteria_met": all(check["criteria_met"] for check in checks.values()),
        "checks": checks,
        "evaluation": evaluation,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = evaluate_plan(
            load_plan(args.plan), args.csv, as_of_ms=time.time_ns() // 1_000_000,
        )
        encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(encoded)
    except (OSError, ValueError, ArithmeticError, csv.Error, RecursionError) as exc:
        parser.exit(2, f"Validation evaluation rejected: {exc}\n")

    print("CRITERIA_MET" if report["criteria_met"] else "CRITERIA_NOT_MET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
