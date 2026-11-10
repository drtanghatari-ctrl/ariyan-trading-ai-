"""Evaluate the exact candle window in a frozen A036 plan offline."""

import argparse
import csv
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path
from zipfile import BadZipFile

from .binance_archive import verify_snapshot
from .evaluation import evaluate_periods
from .market_data import integer, load_candles
from .replay import ReplayConfig
from .validation_engine import verify_engine_sources
from .validation_plan import load_plan, verify_plan
from .validation_timestamp import verify_timestamp
from .validation_witness import load_witness_receipt, verify_witness_receipt

VERSION = "ARIYAN-A037-VALIDATION-EVALUATION-V1"
SOURCE_RECORD_VERSION = "ARIYAN-A041-VALIDATION-EVALUATION-V1"
WITNESS_RECORD_VERSION = "ARIYAN-A044-VALIDATION-EVALUATION-V1"
TIMESTAMP_RECORD_VERSION = "ARIYAN-A046-VALIDATION-EVALUATION-V1"
ARCHIVE_RECORD_VERSION = "ARIYAN-A047-VALIDATION-EVALUATION-V1"


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


def evaluate_plan(plan, csv_path, *, as_of_ms, require_engine_source=False,
                  record_engine_source=False, witness_receipt_path=None,
                  witness_public_key_hex=None, record_witness_receipt=False,
                  binance_snapshot=None):
    """Run A008 from candle bytes and grade both scenarios against the plan."""
    plan = verify_plan(plan)
    spec = plan["spec"]
    start = spec["window"]["start_ms"]
    end = spec["window"]["end_ms"]
    if integer(as_of_ms, "as_of_ms") < end:
        raise ValueError("Evaluation window is still open")
    if (witness_receipt_path is None) != (witness_public_key_hex is None):
        raise ValueError("--witness-receipt and --witness-public-key-hex must be used together")
    if record_witness_receipt and witness_receipt_path is None:
        raise ValueError("--record-witness-receipt requires a witness receipt and key")
    if witness_receipt_path is not None:
        receipt = load_witness_receipt(witness_receipt_path)
        witness_check = verify_witness_receipt(
            plan, receipt, witness_public_key_hex=witness_public_key_hex,
        )
    if require_engine_source or record_engine_source:
        checked_paths = verify_engine_sources(
            Path(__file__).resolve().parents[2], spec["code_commit"],
        )
    if (csv_path is None) == (binance_snapshot is None):
        raise ValueError("Supply either a CSV or a Binance snapshot")
    if binance_snapshot is not None:
        snapshot = verify_snapshot(binance_snapshot)
        snapshot_data = snapshot["dataset"]
        market = spec["market"]
        if (snapshot["instrument"]["symbol"] != market["symbol"]
                or any(snapshot_data[field] != market[field] for field in (
                    "input_format", "timestamp_unit", "interval_ms",
                ))
                or (snapshot_data["first_open_ms"], snapshot_data["last_close_ms"]) != (start, end)):
            raise ValueError("Binance snapshot market or coverage differs from the frozen plan")
        csv_path = Path(binance_snapshot) / snapshot_data["file"]
    dataset = load_candles(csv_path, as_of_ms=end, **spec["market"])
    if binance_snapshot is not None and dataset.raw_sha256 != snapshot_data["raw_sha256"]:
        raise ValueError("Candle bytes differ from the verified Binance snapshot")
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
    report = {
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
    if record_engine_source:
        report["version"] = SOURCE_RECORD_VERSION
        report["engine_source_check"] = {
            "status": "LOCAL_SOURCE_BYTES_MATCH",
            "checked_paths": list(checked_paths),
        }
    if record_witness_receipt:
        canonical_receipt = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("ascii")
        report["version"] = WITNESS_RECORD_VERSION
        report["witness_receipt_check"] = {
            **witness_check,
            "receipt_sha256": hashlib.sha256(canonical_receipt).hexdigest(),
        }
    if binance_snapshot is not None:
        canonical_manifest = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
        report["version"] = ARCHIVE_RECORD_VERSION
        report["archive_snapshot_check"] = {
            "status": "RETAINED_BINANCE_ARCHIVES_REVERIFIED",
            "manifest_sha256": hashlib.sha256(canonical_manifest).hexdigest(),
            "candle_csv_sha256": dataset.raw_sha256,
            "instrument": snapshot["instrument"],
            "source_label": snapshot["source_label"],
            "source_independently_authenticated": False,
        }
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    candles = parser.add_mutually_exclusive_group(required=True)
    candles.add_argument("--csv", type=Path)
    candles.add_argument("--binance-snapshot", type=Path, help="Require a retained A010 snapshot")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="Write a new evaluation report")
    mode.add_argument("--verify-report", type=Path, help="Reproduce a saved evaluation report")
    parser.add_argument("--expected-plan-sha256", help="Separately recorded plan fingerprint")
    parser.add_argument(
        "--require-engine-source", action="store_true",
        help="Require the local replay sources to match the plan's Git commit",
    )
    parser.add_argument(
        "--record-engine-source", action="store_true",
        help="Require the source match and record the checked paths in a versioned report",
    )
    parser.add_argument("--witness-receipt", type=Path, help="Require a signed A042 receipt")
    parser.add_argument("--witness-public-key-hex",
                        help="Expected Ed25519 key obtained independently of the receipt")
    parser.add_argument(
        "--record-witness-receipt", action="store_true",
        help="Record the verified receipt and key fingerprints in a versioned report",
    )
    parser.add_argument("--timestamp-receipt", type=Path, help="Require an RFC 3161 response")
    parser.add_argument("--timestamp-ca-file", type=Path, help="Trusted timestamp CA file")
    parser.add_argument("--expected-timestamp-ca-sha256", help="Independently obtained CA file hash")
    parser.add_argument("--timestamp-tsa-cert", type=Path, help="Optional untrusted TSA certificate")
    args = parser.parse_args(argv)
    if (args.verify_report is None) != (args.expected_plan_sha256 is None):
        parser.error("--verify-report and --expected-plan-sha256 must be used together")
    timestamp_options = (
        args.timestamp_receipt, args.timestamp_ca_file, args.expected_timestamp_ca_sha256,
    )
    use_timestamp = all(value is not None for value in timestamp_options)
    if not use_timestamp and (
        any(value is not None for value in timestamp_options) or args.timestamp_tsa_cert is not None
    ):
        parser.error(
            "--timestamp-receipt, --timestamp-ca-file and "
            "--expected-timestamp-ca-sha256 must be used together"
        )
    try:
        plan = load_plan(args.plan)
        if args.verify_report is not None and plan["plan_sha256"] != args.expected_plan_sha256:
            raise ValueError("Plan does not match the separately recorded fingerprint")
        if use_timestamp:
            timestamp_check = verify_timestamp(
                plan, args.timestamp_receipt, args.timestamp_ca_file,
                expected_ca_sha256=args.expected_timestamp_ca_sha256,
                tsa_cert_path=args.timestamp_tsa_cert,
            )
        report = evaluate_plan(
            plan, args.csv, as_of_ms=time.time_ns() // 1_000_000,
            require_engine_source=args.require_engine_source,
            record_engine_source=args.record_engine_source,
            witness_receipt_path=args.witness_receipt,
            witness_public_key_hex=args.witness_public_key_hex,
            record_witness_receipt=args.record_witness_receipt,
            binance_snapshot=args.binance_snapshot,
        )
        if use_timestamp:
            if args.binance_snapshot is None:
                report["version"] = TIMESTAMP_RECORD_VERSION
            report["plan_timestamp_check"] = timestamp_check
        encoded = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode(
            "ascii"
        )
        if args.verify_report is not None:
            with args.verify_report.open("rb") as stream:
                if stream.read(len(encoded) + 1) != encoded:
                    raise ValueError("Saved report differs from the reproduced report")
        else:
            with args.output.open("xb") as stream:
                stream.write(encoded)
    except (OSError, ValueError, ArithmeticError, csv.Error, RuntimeError, BadZipFile) as exc:
        parser.exit(2, f"Validation evaluation rejected: {exc}\n")

    if args.verify_report is not None:
        print("REPORT_REPRODUCED")
    print("CRITERIA_MET" if report["criteria_met"] else "CRITERIA_NOT_MET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
