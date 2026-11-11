"""Synthetic prices and instruments only; hand-computed expectations."""
import json
import unittest
from dataclasses import replace
from decimal import Decimal as D, localcontext

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P, Side,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.strategies import BuyAndHold, Signal, SmaCross, Strategy

INTERVAL = 60000


def spec(**changes):
    terms = dict(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'BT-001'), display_symbol='SYNTH',
        asset_class=A.INDEX, product=P.CFD, base_label='SYNTHETIC index', quote_currency='USD',
        contract_size='1000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
        price_step='0.01', pip_size='0.01', initial_margin_rate='0.1',
        maintenance_margin_rate='0.05', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-24X7-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=0, effective_until_ms=None,
        source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)
    terms.update(changes)
    return MarginInstrumentSpec(**terms)


def dataset(rows):
    candles = tuple(Candle(i * INTERVAL, D(o), D(h), D(l), D(c), D(1))
                    for i, (o, h, l, c) in enumerate(rows))
    return CandleDataset(candles, 'SYNTH', INTERVAL, 'SYNTHETIC TEST ONLY',
                         len(rows) * INTERVAL, 'a' * 64, 'canonical', 'ms')


UP = [(100, 100, 100, 100), (100, 110, 100, 110), (110, 110, 110, 110)]


class Always(Strategy):
    name = 'always'

    def __init__(self, signal):
        self.signal = signal

    lookback = 1

    def target(self, history):
        return self.signal


class Spy(Strategy):
    name = 'spy'
    lookback = 3

    def __init__(self):
        self.seen = []

    def target(self, history):
        self.seen.append((len(history), history[-1].timestamp_ms,
                          [c.timestamp_ms for c in history]))
        return Signal.LONG


def wave(n):
    rows, price = [], 100
    for i in range(n):
        step = ((i * 7) % 11) - 5 + (3 if (i // 25) % 2 == 0 else -3)
        opened, price = price, max(20, price + step)
        rows.append((opened, max(opened, price) + 1, min(opened, price) - 1, price))
    return rows


class BacktestA035Tests(unittest.TestCase):
    def test_long_trade_without_costs_matches_hand_calculation(self):
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(margin_fraction='0.5'))
        t, = r.trades
        self.assertEqual((t.side, t.lots, t.entry_price, t.exit_price), (Side.LONG, D('0.5'), D(100), D(110)))
        self.assertEqual(t.net_pnl, D(5000))
        self.assertEqual(t.open_ms, INTERVAL)  # decision at close of bar 0 fills at bar 1 open
        self.assertEqual(r.metrics['final_equity'], '15000.000000')
        self.assertEqual(r.metrics['total_return_pct'], '50.000000')
        self.assertEqual(r.metrics['max_drawdown_pct'], '0.000000')
        self.assertEqual(r.metrics['win_rate_pct'], '100.000000')
        self.assertIsNone(r.metrics['profit_factor'])
        self.assertEqual(r.equity_curve[1][1], D(15000))

    def test_spread_commission_and_financing_are_all_charged(self):
        config = BacktestConfig(margin_fraction='0.5', spread='2', commission_per_lot_per_side='3',
                                financing_long_per_lot_per_bar='1')
        r = run_backtest(dataset(UP), spec(), BuyAndHold(), config)
        t, = r.trades
        self.assertEqual((t.lots, t.entry_price, t.exit_price), (D('0.49'), D(101), D(109)))
        self.assertEqual((t.gross_pnl, t.commission, t.financing), (D(3920), D('2.94'), D('0.98')))
        self.assertEqual(t.net_pnl, D('3916.08'))
        self.assertEqual(r.metrics['final_equity'], '13916.080000')
        self.assertEqual(r.metrics['spread_cost'], '980.000000')
        self.assertEqual(r.metrics['commission_cost'], '2.940000')
        self.assertEqual(r.metrics['financing_cost'], '0.980000')
        self.assertEqual(D(r.metrics['final_equity']) - D(10000), t.net_pnl)

    def test_negative_financing_is_a_credit(self):
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(margin_fraction='0.5', financing_long_per_lot_per_bar='-2'))
        self.assertEqual(r.trades[0].financing, D('-2.0'))
        self.assertEqual(r.metrics['final_equity'], '15002.000000')

    def test_short_trade_profits_when_price_falls(self):
        rows = [(100, 100, 100, 100), (100, 100, 90, 90), (90, 90, 90, 90)]
        r = run_backtest(dataset(rows), spec(), Always(Signal.SHORT),
                         BacktestConfig(margin_fraction='0.5'))
        t, = r.trades
        self.assertEqual((t.side, t.net_pnl), (Side.SHORT, D(5000)))

    def test_stop_out_liquidates_at_adverse_extreme_and_blocks_reentry(self):
        rows = [(100, 100, 100, 100), (100, 100, 84, 90), (90, 95, 90, 95), (95, 99, 95, 99)]
        r = run_backtest(dataset(rows), spec(), BuyAndHold(), BacktestConfig(margin_fraction='0.5'))
        t, = r.trades
        self.assertEqual((t.reason, t.exit_price, t.net_pnl), ('STOP_OUT', D(84), D(-8000)))
        self.assertEqual(r.metrics['stop_outs'], 1)
        self.assertFalse(r.metrics['ruined'])
        self.assertEqual(r.metrics['final_equity'], '2000.000000')
        self.assertEqual(r.metrics['bars_simulated'], 4)

    def test_no_stop_out_just_above_maintenance(self):
        rows = [(100, 100, 100, 100), (100, 100, 85, 90), (90, 90, 90, 90)]
        r = run_backtest(dataset(rows), spec(), BuyAndHold(), BacktestConfig(margin_fraction='0.5'))
        self.assertEqual(r.metrics['stop_outs'], 0)
        self.assertEqual(r.trades[0].reason, 'END')

    def test_ruin_ends_the_run_with_a_negative_balance(self):
        rows = [(100, 100, 100, 100), (100, 100, 50, 60), (60, 60, 60, 60), (60, 70, 60, 70)]
        r = run_backtest(dataset(rows), spec(), BuyAndHold(), BacktestConfig(margin_fraction='1'))
        self.assertTrue(r.metrics['ruined'])
        self.assertEqual(r.metrics['bars_simulated'], 2)
        self.assertEqual(r.metrics['final_equity'], '-40000.000000')
        self.assertEqual(len(r.trades), 1)

    def test_shorting_unavailable_ignores_short_signals(self):
        r = run_backtest(dataset(UP), spec(allows_short=False), Always(Signal.SHORT))
        self.assertEqual(r.trades, ())
        self.assertEqual(r.metrics['short_signals_ignored'], 2)  # one per decision bar
        self.assertEqual(r.metrics['final_equity'], '10000.000000')

    def test_position_below_minimum_lot_is_skipped(self):
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(opening_cash='50', margin_fraction='0.5'))
        self.assertEqual(r.trades, ())
        # An unfilled target is retried at each later open while it persists.
        self.assertEqual(r.metrics['skipped_below_min_lot'], 2)

    def test_commission_that_breaks_margin_skips_the_entry(self):
        flat = [(100, 100, 100, 100)] * 3
        r = run_backtest(dataset(flat), spec(), BuyAndHold(),
                         BacktestConfig(margin_fraction='1', commission_per_lot_per_side='5'))
        self.assertEqual(r.trades, ())
        self.assertEqual(r.metrics['skipped_margin'], 2)
        self.assertEqual(r.metrics['final_equity'], '10000.000000')

    def test_maximum_lot_caps_position_size(self):
        r = run_backtest(dataset(UP), spec(maximum_lot='0.25'), BuyAndHold(),
                         BacktestConfig(margin_fraction='1'))
        self.assertEqual(r.trades[0].lots, D('0.25'))

    def test_strategy_only_sees_closed_history_up_to_the_decision_bar(self):
        spy = Spy()
        rows = wave(40)
        run_backtest(dataset(rows), spec(), spy)
        self.assertEqual(len(spy.seen), 40 - 3)  # no decision at the last bar: nothing to fill
        for n, last_ms, stamps in spy.seen:
            self.assertEqual(n, 3)
            self.assertEqual(stamps, [last_ms - 2 * INTERVAL, last_ms - INTERVAL, last_ms])
        self.assertEqual([s[1] for s in spy.seen], [i * INTERVAL for i in range(2, 39)])

    def test_future_bars_cannot_change_earlier_results(self):
        rows = wave(120)
        config = BacktestConfig(margin_fraction='0.2', spread='0.2', liquidate_at_end=False)
        short = run_backtest(dataset(rows[:80]), spec(), SmaCross(3, 8), config)
        altered = rows[:80] + [(p, p + 40, p - 1, p + 30) for p in range(50, 90)]
        longer = run_backtest(dataset(altered), spec(), SmaCross(3, 8), config)
        self.assertEqual(longer.equity_curve[:80], short.equity_curve)
        closed_before = [t for t in longer.trades if t.close_ms <= 79 * INTERVAL]
        self.assertEqual(closed_before, list(short.trades))

    def test_reversal_produces_long_and_short_trades(self):
        v = [(100 - i, 101 - i, 99 - i, 100 - i) for i in range(20)]
        v += [(80 + i, 81 + i, 79 + i, 80 + i) for i in range(30)]
        r = run_backtest(dataset(v), spec(), SmaCross(2, 5), BacktestConfig(margin_fraction='0.1'))
        self.assertEqual({t.side for t in r.trades}, {Side.LONG, Side.SHORT})
        self.assertGreater(r.metrics['trades'], 1)
        self.assertEqual(r.metrics['winning_trades'] + r.metrics['losing_trades'],
                         len([t for t in r.trades if t.net_pnl != 0]))

    def test_metrics_drawdown_and_sharpe(self):
        r = run_backtest(dataset(wave(150)), spec(), SmaCross(3, 8),
                         BacktestConfig(margin_fraction='0.2', spread='0.1', periods_per_year=525600))
        m = r.metrics
        self.assertGreaterEqual(D(m['max_drawdown_pct']), 0)
        self.assertIsNotNone(m['sharpe_per_bar'])
        self.assertIsNotNone(m['sharpe_annualized'])
        peak, worst = r.equity_curve[0][1], D(0)
        for _, e in r.equity_curve:
            peak = max(peak, e)
            worst = max(worst, (peak - e) / peak)
        self.assertEqual(m['max_drawdown_pct'], str((worst * 100).quantize(D('0.000001'))))
        without = run_backtest(dataset(wave(150)), spec(), SmaCross(3, 8),
                               BacktestConfig(margin_fraction='0.2', spread='0.1'))
        self.assertIsNone(without.metrics['sharpe_annualized'])

    def test_costs_reduce_results(self):
        base = BacktestConfig(margin_fraction='0.2')
        costly = BacktestConfig(margin_fraction='0.2', spread='0.5', commission_per_lot_per_side='2')
        a = run_backtest(dataset(wave(150)), spec(), SmaCross(3, 8), base)
        b = run_backtest(dataset(wave(150)), spec(), SmaCross(3, 8), costly)
        self.assertLess(D(b.metrics['final_equity']), D(a.metrics['final_equity']))

    def test_result_is_deterministic_and_context_independent(self):
        a = run_backtest(dataset(wave(100)), spec(), SmaCross(3, 8), BacktestConfig(margin_fraction='0.2'))
        with localcontext() as context:
            context.prec = 4
            b = run_backtest(dataset(wave(100)), spec(), SmaCross(3, 8), BacktestConfig(margin_fraction='0.2'))
        self.assertEqual(a.to_record(), b.to_record())
        self.assertEqual(json.dumps(a.to_record(include_curve=True)), json.dumps(b.to_record(include_curve=True)))

    def test_record_carries_provenance_and_no_approval_claims(self):
        r = run_backtest(dataset(UP), spec(), BuyAndHold())
        record = json.loads(json.dumps(r.to_record()))
        self.assertEqual(record['version'], 'ARIYAN-A035-BACKTEST-V1')
        self.assertFalse(record['investment_evidence'])
        self.assertFalse(record['executable_support_established'])
        p = record['provenance']
        self.assertEqual(p['dataset_sha256'], 'a' * 64)
        self.assertEqual(p['instrument_fingerprint'], spec().fingerprint())
        self.assertEqual(p['strategy'], {'name': 'buy_and_hold', 'params': {}})
        self.assertIn('quote currency', p['currency_note'])
        self.assertNotIn('equity_curve', record)
        self.assertIn('equity_curve', r.to_record(include_curve=True))

    def test_invalid_inputs(self):
        data = dataset(UP)
        for args in ((object(), spec(), BuyAndHold()), (data, object(), BuyAndHold()),
                     (data, spec(), object()), (data, spec(), BuyAndHold(), object())):
            with self.assertRaises(ValueError):
                run_backtest(*args)
        with self.assertRaises(ValueError):
            run_backtest(data, spec(), SmaCross(2, 3))  # needs more than three bars
        with self.assertRaises(ValueError):
            run_backtest(data, spec(effective_from_ms=INTERVAL), BuyAndHold())
        with self.assertRaises(ValueError):
            run_backtest(data, spec(), Always('LONG'))

    def test_invalid_config(self):
        for changes in ({'opening_cash': '0'}, {'opening_cash': '-5'}, {'margin_fraction': '0'},
                        {'margin_fraction': '1.1'}, {'spread': '-1'},
                        {'commission_per_lot_per_side': '-1'}, {'liquidate_at_end': 1},
                        {'periods_per_year': 0}, {'periods_per_year': True},
                        {'financing_long_per_lot_per_bar': 'x'}, {'spread': 1.5}):
            with self.assertRaises((ValueError, TypeError)):
                BacktestConfig(**changes)

    def test_end_of_data_liquidation_can_be_disabled(self):
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(margin_fraction='0.5', liquidate_at_end=False))
        self.assertEqual(r.trades, ())
        self.assertEqual(r.metrics['final_equity'], '15000.000000')


if __name__ == '__main__':
    unittest.main()
