"""A008 fixed-parameter chronological evaluation; offline, no capital authority."""

import argparse
import csv
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from .market_data import CandleDataset, integer, load_candles
from .replay import ReplayConfig, run_replay


def evaluate_periods(dataset, config=None, *, periods=3,
                     stress_fee_bps="20", stress_slippage_bps="10"):
    """Partition all bars into contiguous disjoint periods, then reset each replay.

    Each period includes its own cold-start MA warmup. No prices, positions or
    signals cross boundaries. Configurations must be chosen before evaluation;
    this API cannot establish that the caller has not already seen the data.
    """
    if type(dataset) is not CandleDataset:
        raise ValueError("A validated CandleDataset is required")
    config = ReplayConfig() if config is None else config
    if type(config) is not ReplayConfig:
        raise ValueError("A ReplayConfig is required")
    integer(periods, "periods", 2)
    if periods > 20:
        raise ValueError("At most 20 periods are supported")
    stress = replace(config, fee_bps=stress_fee_bps,
                     slippage_bps=stress_slippage_bps)
    base_costs = (Decimal(config.fee_bps), Decimal(config.slippage_bps))
    stress_costs = (Decimal(stress.fee_bps), Decimal(stress.slippage_bps))
    if any(s < b for b, s in zip(base_costs, stress_costs)) or stress_costs == base_costs:
        raise ValueError("Stress costs must not decrease; at least one must increase")
    width, remainder = divmod(len(dataset.candles), periods)
    if width <= config.long_window:
        raise ValueError("Every period needs long_window + 1 candles")
    results = []
    offset = 0
    for index in range(periods):
        count = width + (index < remainder)
        end = offset + count
        subset = replace(dataset, candles=dataset.candles[offset:end])
        scenarios = {}
        for name, parameters in (("base", config), ("stress", stress)):
            replay = run_replay(subset, parameters)
            scenarios[name] = {
                "config": replay["config"], "summary": replay["summary"],
                "buy_hold": replay["buy_hold"],
            }
        results.append({
            "period": index + 1, "start_index": offset, "end_index_exclusive": end,
            "candles": count, "first_open_ms": subset.candles[0].timestamp_ms,
            "last_close_ms": subset.candles[-1].timestamp_ms + dataset.interval_ms,
            "first_eligible_fill_ms": subset.candles[config.long_window].timestamp_ms,
            "scenarios": scenarios,
        })
        offset = end
    counts = {}
    for name in ("base", "stress"):
        pnl = [Decimal(p["scenarios"][name]["summary"]["net_marked_pnl"]) for p in results]
        counts[name] = {"positive_periods": sum(x > 0 for x in pnl),
                        "negative_periods": sum(x < 0 for x in pnl),
                        "flat_periods": sum(x == 0 for x in pnl)}
    return {
        "version": "ARIYAN-A008-EVALUATION-V1",
        "mode": "OFFLINE_EVALUATION_NO_LIVE_ACTIONS",
        "strategy": "SMA_LEVEL_TEST_STRATEGY_NOT_VALIDATED",
        "dataset": {
            "symbol": dataset.symbol, "source_label": dataset.source,
            "raw_sha256": dataset.raw_sha256,
            "hash_scope": "EXACT_FULL_INPUT_BYTES_NOT_PERIOD_BYTES",
            "source_independently_authenticated": False,
            "input_format": dataset.input_format, "timestamp_unit": dataset.timestamp_unit,
            "interval_ms": dataset.interval_ms, "as_of_ms": dataset.as_of_ms,
            "candles": len(dataset.candles),
        },
        "partition_policy": "CONTIGUOUS_DISJOINT_ALL_BARS_EARLIER_PERIODS_RECEIVE_REMAINDER",
        "portfolio_policy": "RESET_CASH_POSITIONS_SIGNALS_AND_WARMUP_EACH_PERIOD",
        "parameter_selection": "CALLER_FIXED_NO_SEARCH_OR_TRAINING",
        "out_of_sample_status": "NOT_ESTABLISHED_CALLER_PRIOR_DATA_ACCESS_UNKNOWN",
        "live_authorized": False,
        "periods": results, "period_counts": counts,
        "limitations": [
            "Descriptive evaluation, not a profitability certificate or predictability gate.",
            "No training, optimization, walk-forward selection, or statistical significance test.",
            "Each period resets capital; period returns must not be compounded as one account.",
            "Each period includes its own warmup and ends with marked, unliquidated holdings.",
            "Base and stress use the same data and are not independent evidence.",
            "Higher costs can change sizing and trade paths; returns need not decrease monotonically.",
            "Full-allocation buy-and-hold is not risk matched to the strategy.",
            "A007 fill assumptions remain: no depth, latency, partial fills or venue filters.",
            "Period boundaries and parameters chosen after seeing results can cause selection bias.",
            "No minimum sample adequacy or strategy approval is asserted.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--interval-ms", required=True, type=int)
    parser.add_argument("--as-of-ms", required=True, type=int)
    parser.add_argument("--format", choices=("canonical", "binance-spot"), default="canonical")
    parser.add_argument("--timestamp-unit", choices=("ms", "us"), default="ms")
    parser.add_argument("--periods", type=int, default=3)
    parser.add_argument("--output", required=True, type=Path)
    for name, default in (("opening-cash", "10000.00"), ("fee-bps", "10"),
                          ("slippage-bps", "5"), ("max-buy-fraction", "0.10"),
                          ("max-position-fraction", "0.25"),
                          ("stress-fee-bps", "20"), ("stress-slippage-bps", "10")):
        parser.add_argument("--" + name, default=default)
    parser.add_argument("--short-window", type=int, default=3)
    parser.add_argument("--long-window", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        config = ReplayConfig(args.opening_cash, args.fee_bps, args.slippage_bps,
                              args.max_buy_fraction, args.max_position_fraction,
                              args.short_window, args.long_window)
        dataset = load_candles(args.csv, symbol=args.symbol, source=args.source,
                               interval_ms=args.interval_ms, as_of_ms=args.as_of_ms,
                               input_format=args.format, timestamp_unit=args.timestamp_unit)
        report = evaluate_periods(dataset, config, periods=args.periods,
                                  stress_fee_bps=args.stress_fee_bps,
                                  stress_slippage_bps=args.stress_slippage_bps)
        encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    except (OSError, ValueError, TypeError, ArithmeticError, UnicodeError, csv.Error) as exc:
        parser.exit(2, f"Evaluation rejected: {exc}\n")
    print("A008 OFFLINE EVALUATION — NO LIVE FINANCIAL ACTIONS")
    print("Periods:", len(report["periods"]))
    print("Report:", args.output)
    return 0


if __name__ == "__main__":
    main()
