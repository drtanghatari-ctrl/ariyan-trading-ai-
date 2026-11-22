"""Synthetic prices only; the data is built so the right answers are known in advance."""
import json
import unittest
from dataclasses import dataclass
from decimal import Decimal as D

from ariyan_trading.backtest import BacktestConfig
from ariyan_trading.fx_conversion import ConversionLeg
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.session_candles import SessionCandleDataset
from ariyan_trading.sessions import CoverageKind, SessionSchedule, SessionWindow
from ariyan_trading.strategies import Signal, SmaCross, Strategy
from ariyan_trading.walkforward import (
    WalkForwardConfig, _run_window, parameter_grid, walk_forward,
)

I = 60000


def spec(quote='USD'):
    return MarginInstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'WF-001'), display_symbol='SYNTH',
        asset_class=A.INDEX, product=P.CFD, base_label='SYNTHETIC index', quote_currency=quote,
        contract_size='10', lot_step='0.01', minimum_lot='0.01', maximum_lot='1000',
        price_step='0.01', pip_size='0.01', initial_margin_rate='0.1',
        maintenance_margin_rate='0.05', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-24X7-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=0, effective_until_ms=None,
        source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)


def dataset(prices, symbol='SYNTH'):
    candles = tuple(Candle(i * I, D(p), D(p), D(p), D(p), D(1)) for i, p in enumerate(prices))
    return CandleDataset(candles, symbol, I, 'SYNTHETIC TEST ONLY', len(prices) * I, 'f' * 64,
                         'canonical', 'ms')


@dataclass(frozen=True)
class Always(Strategy):
    signal: Signal
    name = 'always'
    lookback = 1

    def target(self, history):
        return self.signal


def reversal(n=120, turn=60):
    return [100 + i if i <= turn else 100 + turn - (i - turn) for i in range(n)]


CFG = BacktestConfig(margin_fraction='0.1')
LONG, SHORT, FLAT = Always(Signal.LONG), Always(Signal.SHORT), Always(Signal.FLAT)


class WalkForwardA038Tests(unittest.TestCase):
    def test_fold_geometry_rolling_and_anchored(self):
        data = dataset(reversal(100, 50))
        rolling = walk_forward(data, spec(), (LONG,), WalkForwardConfig(40, 20), CFG)
        self.assertEqual(len(rolling.folds), 3)
        for fold, (a, b, c, d) in zip(rolling.folds, ((0, 39, 40, 59), (20, 59, 60, 79), (40, 79, 80, 99))):
            self.assertEqual((fold.train_first_ms, fold.train_last_ms, fold.test_first_ms, fold.test_last_ms),
                             (a * I, b * I, c * I, d * I))
        anchored = walk_forward(data, spec(), (LONG,), WalkForwardConfig(40, 20, anchored=True), CFG)
        self.assertEqual([f.train_first_ms for f in anchored.folds], [0, 0, 0])
        self.assertEqual([f.train_last_ms for f in anchored.folds], [39 * I, 59 * I, 79 * I])
        stepped = walk_forward(data, spec(), (LONG,), WalkForwardConfig(40, 20, step_bars=10), CFG)
        self.assertEqual(len(stepped.folds), 5)

    def test_selection_uses_training_data_and_exposes_the_regime_change(self):
        # Rising to bar 60, then falling. Fold 1 trains on the rise (picks LONG), tests on the fall.
        result = walk_forward(dataset(reversal()), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        f0, f1, f2 = result.folds[:3]
        self.assertEqual((f0.selected_index, f1.selected_index), (0, 0))
        self.assertGreater(D(f0.test_return_pct), 0)
        self.assertLess(D(f1.test_return_pct), 0)
        self.assertEqual(f1.test_return_pct, f1.benchmark_return_pct)  # the selection was LONG
        self.assertGreater(D(f1.train_return_pct), 0)
        # Later the fall is in training, so SHORT is chosen and profits.
        self.assertEqual(result.folds[-1].selected_index, 1)
        self.assertGreater(D(result.folds[-1].test_return_pct), 0)
        agg = result.aggregate
        self.assertEqual(agg['folds'], len(result.folds))
        self.assertEqual(agg['distinct_selected_candidates'], 2)
        self.assertEqual(agg['candidates_per_fold'], 2)
        self.assertGreater(D(agg['in_sample_minus_oos_pct']), 0)  # in-sample looks better than OOS

    def test_no_look_ahead_future_and_test_data_cannot_change_selection(self):
        base = reversal(120)
        altered_after = base[:80] + [500 - i * 3 for i in range(40)]   # differs only after bar 79
        a = walk_forward(dataset(base), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        b = walk_forward(dataset(altered_after), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        self.assertEqual([f.to_record() for f in a.folds[:2]], [f.to_record() for f in b.folds[:2]])
        # Altering only fold 0's TEST window (bars 40..59) leaves its selection unchanged.
        tweaked = base[:40] + [100 - i for i in range(20)] + base[60:]
        c = walk_forward(dataset(tweaked), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        self.assertEqual(a.folds[0].selected_index, c.folds[0].selected_index)
        self.assertEqual(a.folds[0].train_return_pct, c.folds[0].train_return_pct)
        self.assertNotEqual(a.folds[0].test_return_pct, c.folds[0].test_return_pct)

    def test_warm_up_bars_precede_the_test_window(self):
        data = dataset(reversal(120, 119))
        strategy = SmaCross(2, 6)
        result = _run_window(data, spec(), strategy, CFG, (), 60, 80)
        self.assertEqual(result.trades[0].open_ms, 60 * I)  # first fill at the first test bar's open
        self.assertEqual(result.provenance['first_ms'], (60 - 6) * I)

    def test_candidates_without_training_trades_are_not_eligible(self):
        only_flat = walk_forward(dataset(reversal()), spec(), (FLAT,), WalkForwardConfig(40, 20), CFG)
        for fold in only_flat.folds:
            self.assertIsNone(fold.selected)
            self.assertEqual((fold.test_return_pct, fold.test_trades), ('0.000000', 0))
            self.assertIn('stayed flat', fold.note)
        self.assertEqual(only_flat.aggregate['folds_with_selection'], 0)
        self.assertEqual(only_flat.aggregate['compounded_oos_return_pct'], '0.000000')
        mixed = walk_forward(dataset(reversal()), spec(), (FLAT, LONG), WalkForwardConfig(40, 20), CFG)
        self.assertEqual({f.selected_index for f in mixed.folds}, {1})
        allowed = walk_forward(dataset(reversal()), spec(), (FLAT, LONG),
                               WalkForwardConfig(40, 20, min_train_trades=0), CFG)
        self.assertEqual(allowed.folds[0].selected_index, 1)  # FLAT earns 0, LONG earns more

    def test_aggregate_matches_manual_compounding(self):
        result = walk_forward(dataset(reversal()), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        growth, bench = D(1), D(1)
        for fold in result.folds:
            growth *= 1 + D(fold.test_return_pct) / 100
            bench *= 1 + D(fold.benchmark_return_pct) / 100
        agg = result.aggregate
        self.assertEqual(agg['compounded_oos_return_pct'], str(((growth - 1) * 100).quantize(D('0.000001'))))
        self.assertEqual(agg['compounded_benchmark_return_pct'], str(((bench - 1) * 100).quantize(D('0.000001'))))
        self.assertEqual(agg['profitable_folds'], sum(1 for f in result.folds if D(f.test_return_pct) > 0))
        self.assertEqual(agg['oos_trades'], sum(f.test_trades for f in result.folds))
        self.assertEqual(agg['worst_fold_return_pct'],
                         str(min(D(f.test_return_pct) for f in result.folds).quantize(D('0.000001'))))

    def test_every_objective_runs(self):
        for objective in ('total_return_pct', 'sharpe_per_bar', 'return_over_drawdown'):
            r = walk_forward(dataset(reversal()), spec(), (LONG, SHORT),
                             WalkForwardConfig(40, 20, objective=objective), CFG)
            self.assertEqual(r.provenance['walk_forward']['objective'], objective)
            self.assertTrue(all(f.selected is not None for f in r.folds[:1]))

    def test_parameter_grid(self):
        grid = parameter_grid(SmaCross, short_window=[2, 3], long_window=[4, 5])
        self.assertEqual(len(grid), 4)
        self.assertEqual({(s.short_window, s.long_window) for s in grid}, {(2, 4), (2, 5), (3, 4), (3, 5)})
        self.assertEqual(len(parameter_grid(SmaCross, short_window=[2, 9], long_window=[5])), 1)
        for kwargs in ({'short_window': [5], 'long_window': [3]}, {'short_window': []}, {'short_window': 3}):
            with self.assertRaises(ValueError):
                parameter_grid(SmaCross, **kwargs)

    def test_grid_search_end_to_end(self):
        grid = parameter_grid(SmaCross, short_window=[2, 3], long_window=[6, 8])
        r = walk_forward(dataset(reversal()), spec(), grid, WalkForwardConfig(40, 20), CFG)
        self.assertEqual(r.aggregate['candidates_per_fold'], 4)
        self.assertEqual(r.provenance['candidates'][0]['name'], 'sma_cross')
        json.dumps(r.to_record())

    def test_validation_errors(self):
        data = dataset(reversal(100, 50))
        good = WalkForwardConfig(40, 20)
        for args in ((object(), spec(), (LONG,), good), (data, spec(), (), good),
                     (data, spec(), [LONG], good), (data, spec(), (object(),), good),
                     (data, spec(), (LONG,), object()),
                     (data, spec(), (SmaCross(2, 40),), good),  # lookback not below train window
                     (data, spec(), (LONG,), WalkForwardConfig(90, 20))):
            with self.assertRaises(ValueError):
                walk_forward(*args)
        for kwargs in ({'train_bars': 1, 'test_bars': 5}, {'train_bars': 5, 'test_bars': 1},
                       {'train_bars': 5, 'test_bars': 5, 'step_bars': 0},
                       {'train_bars': 5, 'test_bars': 5, 'objective': 'luck'},
                       {'train_bars': 5, 'test_bars': 5, 'anchored': 1},
                       {'train_bars': 5, 'test_bars': 5, 'min_train_trades': -1},
                       {'train_bars': True, 'test_bars': 5}):
            with self.assertRaises(ValueError):
                WalkForwardConfig(**kwargs)

    def test_session_dataset_and_conversion_pass_through(self):
        prices = reversal(100, 50)
        candles = tuple(Candle(i * I, D(p), D(p), D(p), D(p), D(1)) for i, p in enumerate(prices))
        schedule = SessionSchedule('SYNTHETIC-ALL', 'UTC', 0, 100 * I, CoverageKind.EXHAUSTIVE,
                                   (SessionWindow(0, 100 * I, 'ALL'),), 'SYNTHETIC', 1)
        sessions = SessionCandleDataset(candles, 'SYNTH', I, 'SYNTHETIC', 100 * I, 'f' * 64, schedule)
        leg = ConversionLeg(dataset([100] * 100, 'USDJPY'), 'JPY', 'USD', True)
        r = walk_forward(sessions, spec('JPY'), (LONG, SHORT), WalkForwardConfig(40, 20),
                         BacktestConfig(margin_fraction='0.1', account_currency='USD'), (leg,))
        self.assertEqual(len(r.folds), 3)
        self.assertEqual(r.provenance['backtest_config']['account_currency'], 'USD')

    def test_result_is_deterministic(self):
        args = (dataset(reversal()), spec(), (LONG, SHORT), WalkForwardConfig(40, 20), CFG)
        self.assertEqual(json.dumps(walk_forward(*args).to_record()), json.dumps(walk_forward(*args).to_record()))
        record = walk_forward(*args).to_record()
        self.assertFalse(record['investment_evidence'])
        self.assertFalse(record['executable_support_established'])
        self.assertEqual(record['provenance']['dataset_sha256'], 'f' * 64)


if __name__ == '__main__':
    unittest.main()
