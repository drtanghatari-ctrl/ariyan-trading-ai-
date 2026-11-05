"""A007 deterministic single-symbol, long-only offline market replay.

No broker, wallet, protected-ledger writes, or live authorization.
MA signals are a test strategy, not an asserted trading advantage.
"""

import argparse
import csv
import json
import time
from collections import deque
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_UP, localcontext
from pathlib import Path

from .market_data import CandleDataset, MAX_VALUE, integer, load_candles, number

CENT = Decimal("0.01")
STEP = Decimal("0.00000001")
BPS = Decimal("10000")
CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)


@dataclass(frozen=True)
class ReplayConfig:
    opening_cash: str = "10000.00"
    fee_bps: str = "10"
    slippage_bps: str = "5"
    max_buy_fraction: str = "0.10"
    max_position_fraction: str = "0.25"
    short_window: int = 3
    long_window: int = 5

    def __post_init__(self):
        with localcontext(CONTEXT):
            cash = number(self.opening_cash, "opening_cash")
            if cash != cash.quantize(CENT):
                raise ValueError("Opening cash requires at most two decimal places")
            for name in ("fee_bps", "slippage_bps"):
                if number(getattr(self, name), name, allow_zero=True) > 1000:
                    raise ValueError("Fee/slippage must be in 0..1000 bps")
            for name in ("max_buy_fraction", "max_position_fraction"):
                if number(getattr(self, name), name) > 1:
                    raise ValueError("Risk fractions must be in (0,1]")
        integer(self.short_window, "short_window", 1)
        integer(self.long_window, "long_window", 2)
        if not self.short_window < self.long_window <= 10_000:
            raise ValueError("Require short_window < long_window <= 10000")


def _cost(quantity, price, fee_rate):
    notional = (quantity * price).quantize(CENT, rounding=ROUND_HALF_EVEN)
    fee = (notional * fee_rate).quantize(CENT, rounding=ROUND_UP)
    return notional, fee


def _buy(cash, units, reference, config):
    """Find maximum eight-place quantity satisfying cash and post-cost caps."""
    fee_rate = Decimal(config.fee_bps) / BPS
    price = reference * (1 + Decimal(config.slippage_bps) / BPS)
    equity = cash + units * reference
    budget = min(cash, equity * Decimal(config.max_buy_fraction)).quantize(
        CENT, rounding=ROUND_DOWN
    )
    fraction = Decimal(config.max_position_fraction)
    maximum = min(MAX_VALUE - units, budget / price)
    if maximum <= 0:
        return None
    lo, hi = 0, int(maximum / STEP)
    while lo < hi:
        middle = (lo + hi + 1) // 2
        quantity = STEP * middle
        notional, fee = _cost(quantity, price, fee_rate)
        outlay = notional + fee
        remaining = cash - outlay
        exposure = (units + quantity) * reference
        if outlay <= budget and exposure <= fraction * (remaining + exposure):
            lo = middle
        else:
            hi = middle - 1
    quantity = STEP * lo
    notional, fee = _cost(quantity, price, fee_rate)
    if quantity == 0 or notional <= 0:
        return None
    return quantity, price, notional, fee


def _sell(units, reference, config):
    if units <= 0:
        return None
    price = reference * (1 - Decimal(config.slippage_bps) / BPS)
    notional, fee = _cost(units, price, Decimal(config.fee_bps) / BPS)
    if notional <= 0 or notional <= fee:
        return None
    return units, price, notional, fee


def _mark(cash, units, close):
    equity = cash + units * close
    if cash < 0 or units < 0 or cash > MAX_VALUE or units > MAX_VALUE or equity > MAX_VALUE:
        raise ValueError("Replay balance exceeds supported range")
    return equity


def _percent(value):
    return str(value.quantize(Decimal("0.000001")))


def run_replay(dataset, config=None):
    """Replay only fully closed bars. A close-derived decision fills next open.

    Final holdings are marked at last close, not automatically liquidated.
    All Decimal operations use an isolated fixed context.
    """
    if type(dataset) is not CandleDataset:
        raise ValueError("A validated CandleDataset is required")
    config = ReplayConfig() if config is None else config
    if type(config) is not ReplayConfig:
        raise ValueError("A ReplayConfig is required")
    if len(dataset.candles) <= config.long_window:
        raise ValueError("Need long_window + 1 candles for a next-open fill")
    with localcontext(CONTEXT):
        return _run(dataset, config)


def _run(dataset, config):
    cash = Decimal(config.opening_cash).quantize(CENT)
    initial = cash
    units = Decimal("0")
    fees = Decimal("0.00")
    slippage = Decimal("0")
    peak = initial
    max_drawdown = Decimal("0")
    baseline_cash, baseline_units = initial, Decimal("0")
    baseline_fees = Decimal("0.00")
    baseline_peak, baseline_drawdown = initial, Decimal("0")
    baseline_attempted, baseline_entry = False, None
    baseline_config = ReplayConfig(
        opening_cash=config.opening_cash, fee_bps=config.fee_bps,
        slippage_bps=config.slippage_bps,
        max_buy_fraction="1", max_position_fraction="1",
        short_window=config.short_window, long_window=config.long_window,
    )
    history = deque(maxlen=config.long_window)
    short_history = deque(maxlen=config.short_window)
    long_sum, short_sum = Decimal("0"), Decimal("0")
    pending = "WARMUP"
    signal_time = None
    trades, curve, decisions = [], [], []
    for index, candle in enumerate(dataset.candles):
        outcome = "WARMUP" if pending == "WARMUP" else "HOLD"
        if index >= config.long_window and not baseline_attempted:
            # One attempt on the exact same first eligible open, no future search.
            baseline_attempted = True
            if dataset.candles[index - 1].volume > 0:
                fill = _buy(baseline_cash, baseline_units, candle.open, baseline_config)
                if fill:
                    qty, price, notional, fee = fill
                    baseline_cash -= notional + fee
                    baseline_units += qty
                    baseline_fees += fee
                    baseline_entry = candle.timestamp_ms
        if pending in ("BUY", "SELL"):
            fill = None
            if dataset.candles[index - 1].volume == 0:
                outcome = "SKIP_PREVIOUS_ZERO_VOLUME"
            elif pending == "BUY":
                fill = _buy(cash, units, candle.open, config)
                outcome = "SKIP_BUY_LIMIT_OR_DUST"
            else:
                fill = _sell(units, candle.open, config)
                outcome = "SKIP_NO_POSITION_OR_DUST"
            if fill:
                quantity, price, notional, fee = fill
                if pending == "BUY":
                    cash -= notional + fee
                    units += quantity
                else:
                    cash += notional - fee
                    units -= quantity
                fees += fee
                slippage += quantity * abs(price - candle.open)
                outcome = "FILLED"
                trades.append({
                    "action": pending,
                    "signal_available_at_ms": signal_time,
                    "fill_timestamp_ms": candle.timestamp_ms,
                    "reference_open": str(candle.open),
                    "fill_price": str(price), "quantity": str(quantity),
                    "notional": str(notional), "fee": str(fee),
                    "cash_after": str(cash), "units_after": str(units),
                })
        equity = _mark(cash, units, candle.close)
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak * 100
        max_drawdown = max(max_drawdown, drawdown)
        baseline_equity = _mark(baseline_cash, baseline_units, candle.close)
        baseline_peak = max(baseline_peak, baseline_equity)
        baseline_drawdown = max(baseline_drawdown,
                                (baseline_peak - baseline_equity) / baseline_peak * 100)
        curve.append({
            "close_timestamp_ms": candle.timestamp_ms + dataset.interval_ms,
            "cash": str(cash), "units": str(units), "equity": str(equity),
            "drawdown_pct": _percent(drawdown),
            "buy_hold_equity": str(baseline_equity),
        })
        if len(history) == config.long_window:
            long_sum -= history[0]
        if len(short_history) == config.short_window:
            short_sum -= short_history[0]
        history.append(candle.close)
        short_history.append(candle.close)
        long_sum += candle.close
        short_sum += candle.close
        if len(history) < config.long_window:
            next_signal = "WARMUP"
        else:
            # Compare means by cross multiplication, without float/division drift.
            difference = short_sum * config.long_window - long_sum * config.short_window
            next_signal = "BUY" if difference > 0 else "SELL" if difference < 0 else "HOLD"
        signal_time = candle.timestamp_ms + dataset.interval_ms
        decisions.append({
            "bar_open_ms": candle.timestamp_ms,
            "execution_of_previous_signal": pending,
            "execution_outcome": outcome,
            "signal_at_close": next_signal,
        })
        pending = next_signal
    final = _mark(cash, units, dataset.candles[-1].close)
    baseline_final = _mark(baseline_cash, baseline_units, dataset.candles[-1].close)
    return {
        "version": "ARIYAN-A007-REPLAY-V1",
        "mode": "OFFLINE_HISTORICAL_REPLAY_NO_LIVE_ACTIONS",
        "strategy": "SMA_LEVEL_TEST_STRATEGY_NOT_VALIDATED",
        "dataset": {
            "symbol": dataset.symbol, "source_label": dataset.source,
            "raw_sha256": dataset.raw_sha256, "input_format": dataset.input_format,
            "timestamp_unit": dataset.timestamp_unit,
            "interval_ms": dataset.interval_ms, "as_of_ms": dataset.as_of_ms,
            "candles": len(dataset.candles),
            "first_open_ms": dataset.candles[0].timestamp_ms,
            "last_close_ms": dataset.candles[-1].timestamp_ms + dataset.interval_ms,
            "source_independently_authenticated": False,
        },
        "config": {
            "opening_cash": str(initial),
            "fee_bps": str(Decimal(config.fee_bps)),
            "slippage_bps": str(Decimal(config.slippage_bps)),
            "max_buy_fraction": str(Decimal(config.max_buy_fraction)),
            "max_position_fraction": str(Decimal(config.max_position_fraction)),
            "short_window": config.short_window, "long_window": config.long_window,
            "quantity_step": str(STEP), "cash_step": str(CENT),
        },
        "summary": {
            "final_cash": str(cash), "final_units": str(units),
            "final_marked_equity": str(final),
            "net_marked_pnl": str(final - initial),
            "return_pct": _percent((final / initial - 1) * 100),
            "max_close_drawdown_pct": _percent(max_drawdown),
            "total_fees": str(fees),
            "modeled_slippage_cost": str(slippage),
            "filled_orders": len(trades),
            "unexecuted_final_signal": pending,
        },
        "buy_hold": {
            "entry_timestamp_ms": baseline_entry,
            "entry_policy": "ONE_ATTEMPT_AT_FIRST_STRATEGY_ELIGIBLE_OPEN",
            "allocation_fraction": "1", "total_fees": str(baseline_fees),
            "final_cash": str(baseline_cash), "final_units": str(baseline_units),
            "final_marked_equity": str(baseline_final),
            "return_pct": _percent((baseline_final / initial - 1) * 100),
            "max_close_drawdown_pct": _percent(baseline_drawdown),
        },
        "limitations": [
            "Single-symbol spot-style long-only simulation; no leverage or shorting.",
            "Signals use completed closes; fills assume immediate next-open execution.",
            "Fixed adverse slippage and fees; no spread, depth, latency or partial fills.",
            "A zero-volume previous bar blocks fills; current-bar volume is future information.",
            "Prior positive volume does not prove fillability at the next open.",
            "No venue tick-size, lot-size, minimum-notional or fee-currency rules.",
            "Buy outlay cap includes fees; post-cost exposure cap is checked at open.",
            "Price gaps can exceed the exposure cap later; sells exit all holdings.",
            "Cash/notional round half-even to cents; fees round up to cents.",
            "Slippage cost is a diagnostic already reflected in fills, not deducted twice.",
            "Final positions are marked at close, without exit costs or forced liquidation.",
            "Drawdown uses closes and opening cash, not intrabar lows.",
            "Buy-and-hold uses full capital; strategy uses smaller exposure limits.",
            "Source labels and byte hashes do not authenticate market data provenance.",
            "No predictability gate, learned model, profitability validation or live authority.",
        ],
        "trades": trades, "equity_curve": curve, "decisions": decisions,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval-ms", required=True, type=int)
    parser.add_argument("--source", required=True)
    parser.add_argument("--as-of-ms", type=int)
    parser.add_argument("--format", choices=("canonical", "binance-spot"), default="canonical")
    parser.add_argument("--timestamp-unit", choices=("ms", "us"), default="ms")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--opening-cash", default="10000.00")
    parser.add_argument("--fee-bps", default="10")
    parser.add_argument("--slippage-bps", default="5")
    parser.add_argument("--max-buy-fraction", default="0.10")
    parser.add_argument("--max-position-fraction", default="0.25")
    parser.add_argument("--short-window", type=int, default=3)
    parser.add_argument("--long-window", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        config = ReplayConfig(
            args.opening_cash, args.fee_bps, args.slippage_bps,
            args.max_buy_fraction, args.max_position_fraction,
            args.short_window, args.long_window,
        )
        dataset = load_candles(
            args.csv, symbol=args.symbol, interval_ms=args.interval_ms,
            source=args.source,
            as_of_ms=args.as_of_ms if args.as_of_ms is not None else time.time_ns() // 1_000_000,
            input_format=args.format, timestamp_unit=args.timestamp_unit,
        )
        report = run_replay(dataset, config)
        encoded = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        # Exclusive creation: never replace an input file or an earlier report.
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    except (OSError, ValueError, TypeError, ArithmeticError, UnicodeError, csv.Error) as exc:
        parser.exit(2, f"Replay rejected: {exc}\n")
    print("A007 OFFLINE REPLAY — NO LIVE FINANCIAL ACTIONS")
    print("Candles:", len(dataset.candles))
    print("Filled orders:", report["summary"]["filled_orders"])
    print("Final marked equity:", report["summary"]["final_marked_equity"])
    print("Return (%):", report["summary"]["return_pct"])
    print("Report:", args.output)
    return 0


if __name__ == "__main__":
    main()
