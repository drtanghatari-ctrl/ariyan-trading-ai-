"""Derive a complete-month Binance archive request from a frozen plan."""

import argparse
import csv
import json
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zipfile import BadZipFile

from .binance_archive import INTERVALS, BinanceSpotRequest, acquire_snapshot
from .validation_plan import load_plan, verify_plan

VERSION = "ARIYAN-A048-VALIDATION-ARCHIVE-REQUEST-V1"
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _month_boundary(epoch_ms):
    utc = EPOCH + timedelta(milliseconds=epoch_ms)
    if utc != datetime(utc.year, utc.month, 1, tzinfo=timezone.utc):
        raise ValueError("The frozen window must start and end on UTC month boundaries")
    return utc


def archive_request_from_plan(plan):
    """Build the A010 request with the exact exclusive plan end as its cutoff."""
    spec = verify_plan(plan)["spec"]
    market = spec["market"]
    if (market["input_format"], market["timestamp_unit"]) != ("canonical", "ms"):
        raise ValueError("A010 snapshots require canonical millisecond candles")
    interval = next((name for name, width in INTERVALS.items()
                     if width == market["interval_ms"]), None)
    if interval is None:
        raise ValueError("The plan interval is unsupported by the Binance archive adapter")

    window = spec["window"]
    start = _month_boundary(window["start_ms"])
    last = _month_boundary(window["end_ms"]) - timedelta(days=1)
    return BinanceSpotRequest(
        market["symbol"], interval, f"{start.year:04d}-{start.month:02d}",
        f"{last.year:04d}-{last.month:02d}", window["end_ms"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--fetch-output", type=Path,
                        help="Explicitly download to a new snapshot directory after the window")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        request = archive_request_from_plan(plan)
        window_closed = time.time_ns() // 1_000_000 >= request.as_of_ms
        result = {
            "version": VERSION,
            "plan_sha256": plan["plan_sha256"],
            "request": asdict(request),
            "window_closed_by_local_clock": window_closed,
        }
        if args.fetch_output is not None:
            if not window_closed:
                raise ValueError("The frozen evaluation window is still open")
            snapshot = acquire_snapshot(request, args.fetch_output)
            result["snapshot_candle_sha256"] = snapshot["dataset"]["raw_sha256"]
    except (OSError, ValueError, ArithmeticError, csv.Error, BadZipFile, RuntimeError) as exc:
        parser.exit(2, f"Plan archive request rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
