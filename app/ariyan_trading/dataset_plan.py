"""A009 offline dataset reservation. No replay, network, or capital authority."""

import argparse
import csv
import json
from dataclasses import asdict, replace
from decimal import Decimal
from pathlib import Path

from .market_data import CandleDataset, integer, load_candles
from .replay import ReplayConfig

MAX_PLAN_BYTES = 65536
EXPOSURES = ("unknown", "previously_inspected", "caller_declares_not_inspected")


def _encoded(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _config_record(config):
    record = asdict(config)
    for name in record:
        if name not in ("short_window", "long_window"):
            record[name] = str(Decimal(record[name]))
    return record


def build_dataset_plan(dataset, *, development_candles, config=None,
                       stress_fee_bps="20", stress_slippage_bps="10",
                       prior_data_access="unknown"):
    """Record one chronological boundary and fixed settings; do not evaluate.

    Both ranges include independent cold-start warmup. Loading validates every
    row, including reserved rows, but does not compute performance. The access
    declaration is a caller assertion, never an established unseen-data claim.
    """
    if type(dataset) is not CandleDataset:
        raise ValueError("A validated CandleDataset is required")
    integer(development_candles, "development_candles", 1)
    config = ReplayConfig() if config is None else config
    if type(config) is not ReplayConfig:
        raise ValueError("A ReplayConfig is required")
    if prior_data_access not in EXPOSURES:
        raise ValueError("Unsupported prior-data-access declaration")
    stress = replace(config, fee_bps=stress_fee_bps, slippage_bps=stress_slippage_bps)
    base_costs = (Decimal(config.fee_bps), Decimal(config.slippage_bps))
    stress_costs = (Decimal(stress.fee_bps), Decimal(stress.slippage_bps))
    if any(s < b for b, s in zip(base_costs, stress_costs)) or stress_costs == base_costs:
        raise ValueError("Stress costs must not decrease; at least one must increase")
    count = len(dataset.candles)
    if min(development_candles, count - development_candles) <= config.long_window:
        raise ValueError("Each range requires long_window + 1 candles")
    ranges = []
    for role, start, end in (("DEVELOPMENT", 0, development_candles),
                             ("RESERVED", development_candles, count)):
        ranges.append({
            "role": role, "start_index": start, "end_index_exclusive": end,
            "candles": end - start,
            "first_open_ms": dataset.candles[start].timestamp_ms,
            "last_close_ms": dataset.candles[end - 1].timestamp_ms + dataset.interval_ms,
            "first_eligible_fill_ms": dataset.candles[start + config.long_window].timestamp_ms,
        })
    return {
        "version": "ARIYAN-A009-DATASET-PLAN-V1",
        "mode": "OFFLINE_RESERVATION_NO_EVALUATION",
        "strategy": "SMA_LEVEL_TEST_STRATEGY_NOT_VALIDATED",
        "dataset": {
            "symbol": dataset.symbol, "source_label": dataset.source,
            "raw_sha256": dataset.raw_sha256,
            "hash_scope": "EXACT_FULL_INPUT_BYTES_NOT_RANGE_BYTES",
            "source_independently_authenticated": False,
            "input_format": dataset.input_format, "timestamp_unit": dataset.timestamp_unit,
            "interval_ms": dataset.interval_ms, "as_of_ms": dataset.as_of_ms,
            "candles": count,
        },
        "config": _config_record(config), "stress_config": _config_record(stress),
        "ranges": ranges,
        "boundary_policy": "CONTIGUOUS_DISJOINT_ALL_BARS_DEVELOPMENT_THEN_RESERVED",
        "replay_policy": "SEPARATE_COLD_START_NO_CROSS_BOUNDARY_WARMUP_OR_POSITIONS",
        "prior_data_access": prior_data_access,
        "out_of_sample_status": "NOT_ESTABLISHED_CALLER_ASSERTION_ONLY",
        "reservation_enforced_by_runtime": False,
        "live_authorized": False,
        "limitations": [
            "No replay, performance measurement, selection, optimization or trading occurs.",
            "The full CSV is parsed for data integrity, including reserved rows.",
            "Reservation does not establish that anyone has avoided seeing the data.",
            "A007 and A008 remain callable directly; this plan is not an access-control gate.",
            "This unsigned file can be edited or recreated; no authenticated publication time.",
            "Byte hashes detect input changes, not independent source authenticity.",
            "Minimum range length enables replay mechanically, not statistical adequacy.",
            "Changing settings or boundaries after viewing results creates a different experiment.",
            "No profitability, predictability, strategy approval or live-readiness claim.",
        ],
    }


def verify_dataset_plan(dataset, plan):
    """Rebuild and compare all recorded fields, including types; no approval."""
    if type(plan) is not dict:
        raise ValueError("Plan must be an object")
    try:
        config = ReplayConfig(**plan["config"])
        expected = build_dataset_plan(
            dataset, development_candles=plan["ranges"][0]["end_index_exclusive"],
            config=config, stress_fee_bps=plan["stress_config"]["fee_bps"],
            stress_slippage_bps=plan["stress_config"]["slippage_bps"],
            prior_data_access=plan["prior_data_access"],
        )
        if _encoded(plan) != _encoded(expected):
            raise ValueError("Plan does not match current input or supported contract")
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Malformed dataset plan") from exc
    return expected


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Non-finite JSON constant")


def read_dataset_plan(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_PLAN_BYTES + 1)
    if len(raw) > MAX_PLAN_BYTES:
        raise ValueError("Plan exceeds 64 KiB limit")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--interval-ms", required=True, type=int)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--format", choices=("canonical", "binance-spot"), default="canonical")
    parser.add_argument("--timestamp-unit", choices=("ms", "us"), default="ms")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--development-candles", required=True, type=int)
    create.add_argument("--prior-data-access", choices=EXPOSURES, default="unknown")
    create.add_argument("--output", required=True, type=Path)
    for name, default in (("opening-cash", "10000.00"), ("fee-bps", "10"),
                          ("slippage-bps", "5"), ("max-buy-fraction", "0.10"),
                          ("max-position-fraction", "0.25"),
                          ("stress-fee-bps", "20"), ("stress-slippage-bps", "10")):
        create.add_argument("--" + name, default=default)
    create.add_argument("--short-window", type=int, default=3)
    create.add_argument("--long-window", type=int, default=5)
    verify = commands.add_parser("verify")
    verify.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        dataset = load_candles(args.csv, symbol=args.symbol, source=args.source,
                               interval_ms=args.interval_ms, as_of_ms=args.as_of_ms,
                               input_format=args.format, timestamp_unit=args.timestamp_unit)
        if args.command == "verify":
            verify_dataset_plan(dataset, read_dataset_plan(args.plan))
            print("A009 INPUT MATCHES PLAN — NO EVALUATION OR TRADING APPROVAL")
        else:
            config = ReplayConfig(args.opening_cash, args.fee_bps, args.slippage_bps,
                                  args.max_buy_fraction, args.max_position_fraction,
                                  args.short_window, args.long_window)
            plan = build_dataset_plan(dataset, development_candles=args.development_candles,
                                      config=config, stress_fee_bps=args.stress_fee_bps,
                                      stress_slippage_bps=args.stress_slippage_bps,
                                      prior_data_access=args.prior_data_access)
            encoded = _encoded(plan)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
            print("A009 DATASET PLAN CREATED — NO PERFORMANCE EVALUATION")
            print("Plan:", args.output)
    except (OSError, ValueError, TypeError, ArithmeticError, UnicodeError, csv.Error,
            RecursionError) as exc:
        parser.exit(2, f"Dataset plan rejected: {exc}\n")
    return 0


if __name__ == "__main__":
    main()
