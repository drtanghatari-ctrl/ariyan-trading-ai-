"""Freeze or verify an offline A008 prospective evaluation plan."""

import argparse
import hashlib
import json
import re
import time
from dataclasses import fields, replace
from decimal import Decimal
from pathlib import Path

from .market_data import MAX_ROWS, integer, number
from .replay import ReplayConfig

VERSION = "ARIYAN-A036-VALIDATION-PLAN-V1"
MAX_PLAN_BYTES = 65536
MAX_TIMESTAMP_MS = 253_402_300_799_000
CONFIG_FIELDS = {field.name for field in fields(ReplayConfig)}
WINDOW_FIELDS = {"short_window", "long_window"}


def _require_fields(value, expected, name):
    if type(value) is not dict or value.keys() != expected:
        raise ValueError(f"{name} has missing or unsupported fields")


def _require_decimal_text(value, name):
    if type(value) is not str or not re.fullmatch(
        r"[0-9]{1,24}(?:\.[0-9]{1,12})?", value
    ):
        raise ValueError(f"{name} must be decimal text")
    return number(value, name, allow_zero=True)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _validate_spec(spec, created_at_ms):
    _require_fields(spec, {
        "code_commit", "market", "window", "config", "stress_costs", "periods", "criteria",
    }, "spec")
    if type(spec["code_commit"]) is not str or not re.fullmatch(
        r"[0-9a-f]{40}", spec["code_commit"]
    ):
        raise ValueError("code_commit must be a full lowercase Git commit ID")

    market = spec["market"]
    _require_fields(market, {
        "symbol", "source", "interval_ms", "input_format", "timestamp_unit",
    }, "market")
    if type(market["symbol"]) is not str or not re.fullmatch(
        r"[A-Z0-9][A-Z0-9_.:/-]{0,39}", market["symbol"]
    ):
        raise ValueError("Invalid market symbol")
    source = market["source"]
    if type(source) is not str or not source.strip() or len(source) > 2048:
        raise ValueError("A nonempty market source label is required")
    interval = integer(market["interval_ms"], "interval_ms", 1)
    if (market["input_format"], market["timestamp_unit"]) not in (
        ("canonical", "ms"), ("binance-spot", "ms"), ("binance-spot", "us"),
    ):
        raise ValueError("Unsupported candle format and timestamp unit")

    window = spec["window"]
    _require_fields(window, {"start_ms", "end_ms"}, "window")
    start = integer(window["start_ms"], "start_ms", 1)
    end = integer(window["end_ms"], "end_ms", 1)
    if not created_at_ms < start < end <= MAX_TIMESTAMP_MS:
        raise ValueError("Require creation before the evaluation window")
    if start % interval or end % interval:
        raise ValueError("Evaluation window boundaries must align with the candle interval")

    config_record = spec["config"]
    _require_fields(config_record, CONFIG_FIELDS, "config")
    for name in sorted(CONFIG_FIELDS - WINDOW_FIELDS):
        _require_decimal_text(config_record[name], name)
    config = ReplayConfig(**config_record)
    stress_costs = spec["stress_costs"]
    _require_fields(stress_costs, {"fee_bps", "slippage_bps"}, "stress_costs")
    for name, value in stress_costs.items():
        _require_decimal_text(value, name)
    stress = replace(config, **stress_costs)
    base_pair = (Decimal(config.fee_bps), Decimal(config.slippage_bps))
    stress_pair = (Decimal(stress.fee_bps), Decimal(stress.slippage_bps))
    if stress_pair == base_pair or any(s < b for b, s in zip(base_pair, stress_pair)):
        raise ValueError("Stress costs must not decrease and at least one must increase")

    periods = integer(spec["periods"], "periods", 2)
    candles = (end - start) // interval
    if periods > 20 or candles > MAX_ROWS:
        raise ValueError("Plan exceeds A007/A008 candle or period limits")
    if candles // periods <= config.long_window:
        raise ValueError("Each period needs long_window + 1 candles")

    criteria = spec["criteria"]
    _require_fields(criteria, {
        "min_positive_periods", "min_filled_orders_per_period", "max_close_drawdown_pct",
    }, "criteria")
    if integer(criteria["min_positive_periods"], "min_positive_periods", 1) > periods:
        raise ValueError("min_positive_periods exceeds the number of periods")
    min_fills = integer(criteria["min_filled_orders_per_period"],
                        "min_filled_orders_per_period", 1)
    if min_fills > candles // periods - config.long_window:
        raise ValueError("Minimum fills exceed eligible bars in the shortest period")
    if _require_decimal_text(criteria["max_close_drawdown_pct"],
                             "max_close_drawdown_pct") > 100:
        raise ValueError("max_close_drawdown_pct must be in 0..100")


def freeze_plan(spec, *, created_at_ms):
    """Bind a validated specification to a caller-supplied local timestamp."""
    integer(created_at_ms, "created_at_ms")
    _validate_spec(spec, created_at_ms)
    payload = {
        "version": VERSION,
        "strategy": "A007_SMA_LEVEL_TEST_STRATEGY",
        "evaluation": "A008_FIXED_PERIOD_BASE_AND_STRESS",
        "created_at_ms": created_at_ms,
        "spec": spec,
    }
    encoded = _canonical(payload)
    return {**json.loads(encoded), "plan_sha256": hashlib.sha256(encoded).hexdigest()}


def verify_plan(plan):
    """Rebuild the plan and check its fingerprint and complete record shape."""
    _require_fields(plan, {
        "version", "strategy", "evaluation", "created_at_ms", "spec", "plan_sha256",
    }, "plan")
    expected = freeze_plan(plan["spec"], created_at_ms=plan["created_at_ms"])
    if plan != expected:
        raise ValueError("Plan does not match its fingerprint or supported contract")
    return expected


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key!r}")
        value[key] = item
    return value


def _read(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError("Plan input exceeds 64 KiB")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("spec", type=Path)
    freeze.add_argument("output", type=Path)
    verify = commands.add_parser("verify")
    verify.add_argument("plan", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze":
            spec = _read(args.spec)
            plan = freeze_plan(spec, created_at_ms=time.time_ns() // 1_000_000)
            with args.output.open("xb") as stream:
                stream.write(_canonical(plan) + b"\n")
        else:
            plan = verify_plan(_read(args.plan))
    except (OSError, ValueError, ArithmeticError, RecursionError) as exc:
        parser.exit(2, f"Validation plan rejected: {exc}\n")
    print(plan["plan_sha256"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
