"""Economic identities, chronology, and causal behavior of offline replay."""

import json
import random
import unittest
from dataclasses import replace
from decimal import Decimal, ROUND_DOWN, ROUND_UP, localcontext

from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.replay import ReplayConfig, run_replay

D = Decimal


def fixture(closes, opens=None, volumes=None):
    candles = []
    for index, close in enumerate(closes):
        close = D(str(close))
        opened = D(str(opens[index])) if opens is not None else close
        volume = D(str(volumes[index])) if volumes is not None else D("10")
        candles.append(Candle(index * 60000, opened, max(opened, close),
                              min(opened, close), close, volume))
    return CandleDataset(tuple(candles), "SYNTHETIC", 60000,
                         "synthetic unit-test fixture", len(candles) * 60000,
                         "0" * 64, "canonical", "ms")


class ReplayA007Tests(unittest.TestCase):
    def test_hand_calculated_round_trip_and_warmup(self):
        data = fixture([100, 100, 110, 100, 90, 80, 100], opens=[100] * 7)
        config = ReplayConfig(opening_cash="1000", fee_bps="0", slippage_bps="0",
                              short_window=2, long_window=3)
        result = run_replay(data, config)
        trades = result["trades"]
        self.assertEqual([t["action"] for t in trades], ["BUY", "BUY", "SELL"])
        self.assertEqual([D(t["quantity"]) for t in trades], [D("1"), D("1"), D("2")])
        self.assertEqual(D(result["summary"]["final_cash"]), D("1000"))
        self.assertEqual(D(result["summary"]["final_units"]), 0)
        self.assertEqual(trades[0]["fill_timestamp_ms"], 180000)
        for trade in trades:
            self.assertEqual(trade["signal_available_at_ms"], trade["fill_timestamp_ms"])

    def test_flat_prices_produce_no_orders(self):
        result = run_replay(fixture([100] * 12))
        self.assertEqual(result["trades"], [])
        self.assertEqual(D(result["summary"]["final_marked_equity"]), 10000)
        self.assertLess(D(result["buy_hold"]["return_pct"]), 0)

    def test_costs_and_cash_movements_reconcile(self):
        data = fixture([100,100,110,100,90,80,100], opens=[100] * 7)
        config = ReplayConfig(opening_cash="1000", fee_bps="100", slippage_bps="100",
                              short_window=2, long_window=3)
        result = run_replay(data, config)
        cash, units, fees, slip = D("1000"), D("0"), D("0"), D("0")
        for trade in result["trades"]:
            q, p, fee = D(trade["quantity"]), D(trade["fill_price"]), D(trade["fee"])
            notional = (q * p).quantize(D("0.01"))
            self.assertEqual(notional, D(trade["notional"]))
            self.assertEqual(fee, (notional * D("0.01")).quantize(D("0.01"), rounding=ROUND_UP))
            if trade["action"] == "BUY":
                self.assertEqual(p, D("101"))
                cash -= notional + fee
                units += q
            else:
                self.assertEqual(p, D("99"))
                cash += notional - fee
                units -= q
            fees += fee
            slip += q * abs(p - D("100"))
            self.assertEqual(D(trade["cash_after"]), cash)
            self.assertEqual(D(trade["units_after"]), units)
        self.assertEqual(D(result["summary"]["total_fees"]), fees)
        self.assertEqual(D(result["summary"]["modeled_slippage_cost"]), slip)
        self.assertLess(D(result["summary"]["final_cash"]), 1000)

    def test_future_suffix_does_not_change_past_fills_or_curve(self):
        prefix = [100,101,102,103,104,105,106,107]
        long = fixture(prefix + [900, 1, 800, 2])
        short = fixture(prefix)
        a, b = run_replay(short), run_replay(long)
        self.assertEqual(a["trades"], [t for t in b["trades"] if t["fill_timestamp_ms"] < 8 * 60000])
        self.assertEqual(a["equity_curve"], b["equity_curve"][:8])
        self.assertEqual(a["decisions"], b["decisions"][:8])

    def test_fill_does_not_see_current_close_high_low_or_final_volume(self):
        a = fixture([100,101,102,103,104,105])
        bars = list(a.candles)
        bars[-1] = replace(bars[-1], high=D("1000"), low=D("1"),
                           close=D("1"), volume=D("0"))
        b = replace(a, candles=tuple(bars))
        self.assertEqual(run_replay(a)["trades"], run_replay(b)["trades"])

    def test_previous_zero_volume_blocks_next_open_only(self):
        a = fixture([100,101,102,103,104,105,106], volumes=[10,10,10,10,0,10,10])
        result = run_replay(a)
        self.assertEqual(result["decisions"][5]["execution_outcome"], "SKIP_PREVIOUS_ZERO_VOLUME")
        self.assertEqual(result["trades"][0]["fill_timestamp_ms"], 360000)
        # Benchmark does not search forward to a convenient later entry.
        self.assertIsNone(result["buy_hold"]["entry_timestamp_ms"])

    def test_risk_caps_include_fees_and_use_post_cost_equity(self):
        data = fixture(list(range(100, 125)))
        config = ReplayConfig(fee_bps="1000", slippage_bps="1000",
                              max_buy_fraction="0.10", max_position_fraction="0.25")
        result = run_replay(data, config)
        cash, units = D("10000"), D("0")
        for trade in result["trades"]:
            reference = D(trade["reference_open"])
            prior_equity = cash + units * reference
            outlay = D(trade["notional"]) + D(trade["fee"])
            self.assertLessEqual(outlay, (prior_equity * D("0.10")).quantize(D("0.01"), rounding=ROUND_DOWN))
            cash, units = D(trade["cash_after"]), D(trade["units_after"])
            self.assertLessEqual(units * reference, D("0.25") * (cash + units * reference))

    def test_tiny_budget_cannot_create_free_units(self):
        result = run_replay(fixture(list(range(100, 110))), ReplayConfig(opening_cash="0.01"))
        self.assertEqual(result["trades"], [])
        self.assertEqual(D(result["summary"]["final_units"]), 0)

    def test_final_position_is_marked_without_future_liquidation(self):
        result = run_replay(fixture([100,101,102,103,104,105]))
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["action"], "BUY")
        summary = result["summary"]
        self.assertGreater(D(summary["final_units"]), 0)
        self.assertEqual(D(summary["final_marked_equity"]),
                         D(summary["final_cash"]) + D(summary["final_units"]) * 105)
        self.assertEqual(summary["unexecuted_final_signal"], "BUY")

    def test_drawdown_includes_initial_capital_and_matches_curve(self):
        result = run_replay(fixture([100,101,102,103,104,105,50,40,30]))
        peak, drawdown = D("10000"), D("0")
        for row in result["equity_curve"]:
            equity = D(row["equity"])
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak * 100)
        self.assertEqual(D(result["summary"]["max_close_drawdown_pct"]), drawdown.quantize(D("0.000001")))
        self.assertGreater(drawdown, 0)

    def test_decimal_context_and_traps_do_not_change_results(self):
        data = fixture([100,101,102,103,104,105,106,50,40])
        normal = run_replay(data)
        with localcontext() as ctx:
            ctx.prec = 3
            ctx.rounding = ROUND_UP
            for signal in ctx.traps:
                ctx.traps[signal] = True
            result = run_replay(data, ReplayConfig())
        self.assertEqual(result, normal)

    def test_invalid_configuration_and_wrong_objects_rejected(self):
        for kwargs in [dict(opening_cash=True), dict(opening_cash="1.001"),
                       dict(fee_bps="-1"), dict(fee_bps="1001"),
                       dict(slippage_bps="NaN"), dict(slippage_bps="1001"),
                       dict(max_buy_fraction="0"), dict(max_position_fraction="1.01"),
                       dict(short_window=True), dict(short_window=5),
                       dict(long_window=10001), dict(fee_bps=0.1)]:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                ReplayConfig(**kwargs)
        with self.assertRaises(ValueError):
            run_replay(object())
        with self.assertRaises(ValueError):
            run_replay(fixture([100] * 5))
        with self.assertRaises(ValueError):
            run_replay(fixture([100] * 6), object())

    def test_seeded_price_paths_preserve_accounting_invariants(self):
        rng = random.Random(7007)
        for _ in range(8):
            closes = [rng.randrange(100, 10000) for _ in range(80)]
            data = fixture(closes)
            result = run_replay(data)
            fees = sum((D(t["fee"]) for t in result["trades"]), D("0"))
            self.assertEqual(fees, D(result["summary"]["total_fees"]))
            for candle, row in zip(data.candles, result["equity_curve"]):
                cash, units = D(row["cash"]), D(row["units"])
                self.assertGreaterEqual(cash, 0)
                self.assertGreaterEqual(units, 0)
                self.assertEqual(D(row["equity"]), cash + units * candle.close)
        json.dumps(result, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
