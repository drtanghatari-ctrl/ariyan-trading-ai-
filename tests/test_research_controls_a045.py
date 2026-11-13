"""A045 tests: registry, locked holdout, scorecard, deflated Sharpe. Synthetic data, hand-derived values."""
import json
import os
import tempfile
import unittest
from decimal import Decimal as D
from types import SimpleNamespace as NS

from ariyan_trading.backtest import BacktestConfig
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.research_controls import (
    DAY_MS, ExperimentRegistry, HoldoutAlreadyUsed, RegistryError, development_dataset, final_holdout_test,
    holdout_start_index, log_development_experiment,
)
from ariyan_trading.scorecard import (
    deflated_sharpe, expected_max_sharpe, probabilistic_sharpe, scorecard,
)
from ariyan_trading.strategies_extra import TrendFilter

SPEC = MarginInstrumentSpec(
    identity=InstrumentIdentity('SYNTHETIC-BROKER', 'X-001'), display_symbol='SYNTH', asset_class=A.INDEX,
    product=P.CFD, base_label='SYNTHETIC index', quote_currency='USD', contract_size='1000', lot_step='0.01',
    minimum_lot='0.01', maximum_lot='100', price_step='0.01', pip_size='0.01', initial_margin_rate='0.1',
    maintenance_margin_rate='0.05', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
    commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-SESSIONS-V1',
    timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE', effective_from_ms=0,
    effective_until_ms=None, source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)


def dataset(bars=800):
    candles = []
    for i in range(bars):
        c = D(100 + (i % 40) - (i % 7) * 2 + i // 10)
        candles.append(Candle(i * DAY_MS, c, c, c, c, D(1)))
    return CandleDataset(tuple(candles), 'SYNTH', DAY_MS, 'S', (bars + 1) * DAY_MS, 'd' * 64, 'canonical', 'ms')


def curve(values, start_ms=0):
    return tuple((start_ms + i * DAY_MS, D(str(v))) for i, v in enumerate(values))


def fake(values, pnls=(), start_ms=0):
    return NS(equity_curve=curve(values, start_ms), trades=tuple(NS(net_pnl=D(str(p))) for p in pnls))


class RegistryTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        handle.close()
        os.unlink(handle.name)
        self.path = handle.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.reg = ExperimentRegistry(self.path, clock_ms=lambda: 5)

    def test_chain_trials_and_sharpes(self):
        self.reg.log('EXPERIMENT', 'fam', 'a' * 64, {'n_trials': 50}, {'sharpe_per_bar': '0.02'})
        self.reg.log('EXPERIMENT', 'fam', 'a' * 64, {}, {'sharpe_per_bar': '-0.01'}, 'failed idea')
        self.reg.log('EXPERIMENT', 'other', 'b' * 64, {'n_trials': 3}, {})
        self.assertEqual(self.reg.trials('fam'), 51)
        self.assertEqual(self.reg.trials(), 54)
        self.assertEqual(self.reg.trial_sharpes('fam'), [0.02, -0.01])
        self.assertEqual([r['seq'] for r in self.reg.records()], [1, 2, 3])

    def test_any_edit_deletion_or_reorder_is_detected(self):
        for i in range(3):
            self.reg.log('EXPERIMENT', 'fam', 'a' * 64, {}, {'sharpe_per_bar': str(i)})
        with open(self.path) as stream:
            lines = stream.read().splitlines()
        cases = {
            'edit': [lines[0].replace('"0"', '"9"')] + lines[1:],
            'delete_first': lines[1:],
            'reorder': [lines[1], lines[0], lines[2]],
            'garbage': lines + ['not json'],
        }
        for name, content in cases.items():
            with open(self.path, 'w') as stream:
                stream.write('\n'.join(content) + '\n')
            with self.assertRaises(RegistryError, msg=name):
                self.reg.records()

    def test_bad_kind_and_missing_family(self):
        with self.assertRaises(RegistryError):
            self.reg.log('GUESS', 'fam', 'a' * 64, {})
        with self.assertRaises(RegistryError):
            self.reg.log('EXPERIMENT', '', 'a' * 64, {})


class HoldoutTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        handle.close()
        os.unlink(handle.name)
        self.path = handle.name
        self.addCleanup(lambda: os.path.exists(self.path) and os.unlink(self.path))
        self.reg = ExperimentRegistry(self.path, clock_ms=lambda: 5)
        self.ds = dataset()

    def test_split_and_development_logging_guard(self):
        start = holdout_start_index(self.ds)
        self.assertEqual(start, 434)                                  # last 365 days begin at bar 434
        dev = development_dataset(self.ds, start)
        self.assertEqual(len(dev.candles), 434)
        holdout_ms = self.ds.candles[start].timestamp_ms
        log_development_experiment(self.reg, dev, holdout_ms, 'fam', {'strategy': 'x'}, {'sharpe_per_bar': '0.01'})
        with self.assertRaisesRegex(RegistryError, 'locked holdout'):
            log_development_experiment(self.reg, self.ds, holdout_ms, 'fam', {}, {})
        self.assertEqual(self.reg.records()[0]['config']['last_candle_ms'], dev.candles[-1].timestamp_ms)

    def test_final_test_runs_once_for_any_strategy(self):
        start = holdout_start_index(self.ds)
        config = BacktestConfig(margin_fraction='0.2')
        result, contaminated = final_holdout_test(self.reg, self.ds, start, TrendFilter(20, True), SPEC,
                                                  config, 'frozen-v1', 'fam')
        self.assertFalse(contaminated)
        self.assertEqual(len(result.folds), 1)
        self.assertEqual(self.reg.records()[-1]['kind'], 'FINAL_HOLDOUT')
        with self.assertRaises(HoldoutAlreadyUsed):
            final_holdout_test(self.reg, self.ds, start, TrendFilter(50, True), SPEC, config, 'frozen-v2', 'fam')
        self.assertEqual(len(self.reg.records()), 1)                  # nothing logged for the refusal

    def test_disclosed_contamination_is_flagged(self):
        self.reg.log('DISCLOSURE', 'fam', 'd' * 64, {'symbol': 'SYNTH', 'contaminated_holdout': True},
                     None, 'full sample was evaluated before the holdout was locked')
        _, contaminated = final_holdout_test(self.reg, self.ds, holdout_start_index(self.ds), TrendFilter(20, True),
                                             SPEC, BacktestConfig(margin_fraction='0.2'), 'frozen', 'fam')
        self.assertTrue(contaminated)
        self.assertTrue(self.reg.records()[-1]['config']['contaminated'])


class ScorecardTests(unittest.TestCase):
    def test_constant_growth(self):
        card = scorecard(fake([100 * 1.01 ** i for i in range(253)]), 252, bootstrap=50)
        self.assertAlmostEqual(card['annualised_return'], 1.01 ** 252 - 1, places=6)
        self.assertEqual((card['max_drawdown'], card['max_drawdown_duration_bars']), (0.0, 0))
        self.assertIsNone(card['sharpe_per_bar'])                     # zero volatility: no ratio, not infinity

    def test_drawdown_depth_duration_and_recovery(self):
        card = scorecard(fake([100] * 30 + [110, 99, 104.5, 110, 121]), 252, bootstrap=20)
        self.assertAlmostEqual(card['max_drawdown'], 0.10, places=9)
        self.assertEqual(card['max_drawdown_duration_bars'], 2)
        self.assertEqual(card['max_drawdown_recovery_bars'], 2)
        self.assertIsNone(card['annualised_return'])                  # under one year of data

    def test_trade_statistics_report_win_rate_with_payoff(self):
        card = scorecard(fake([100 + i % 3 for i in range(60)], pnls=[10, -5, 10, -5]), 252, bootstrap=20)
        self.assertEqual((card['win_rate'], card['average_win'], card['average_loss']), (0.5, 10.0, -5.0))
        self.assertEqual((card['payoff_ratio'], card['profit_factor'], card['expectancy_per_trade']), (2.0, 2.0, 2.5))

    def test_yearly_returns_and_expected_shortfall(self):
        year = 365 * DAY_MS
        values = [100 + (i % 5) for i in range(40)] + [120] * 10
        card = scorecard(fake(values, start_ms=year * 10 - 20 * DAY_MS), 252, bootstrap=20)
        self.assertEqual(sorted(card['yearly_returns']), ['1979', '1980'])
        self.assertLess(card['expected_shortfall_5pct_per_bar'], 0)
        self.assertLessEqual(card['worst_bar'], card['expected_shortfall_5pct_per_bar'])

    def test_bootstrap_is_reproducible_and_brackets_a_sensible_range(self):
        values = [100]
        for i in range(400):
            values.append(values[-1] * (1.003 if i % 3 else 0.994))
        a = scorecard(fake(values), 252, bootstrap=200, seed=7)
        b = scorecard(fake(values), 252, bootstrap=200, seed=7)
        self.assertEqual(a['sharpe_annualised_ci'], b['sharpe_annualised_ci'])
        low, high = a['sharpe_annualised_ci']
        self.assertLess(low, high)
        self.assertLess(a['annualised_return_ci'][0], a['annualised_return_ci'][1])

    def test_validation(self):
        with self.assertRaises(ValueError):
            scorecard(fake([100] * 10), 252)
        with self.assertRaises(ValueError):
            scorecard(fake([100] * 40), 0)


class DeflatedSharpeTests(unittest.TestCase):
    def test_probabilistic_sharpe_values_and_monotonicity(self):
        self.assertAlmostEqual(probabilistic_sharpe(0.0, 100, 0.0, 3.0), 0.5, places=12)
        self.assertAlmostEqual(probabilistic_sharpe(0.1, 100, 0.0, 3.0), 0.8395, places=3)   # hand: z = 0.9925
        self.assertGreater(probabilistic_sharpe(0.2, 100, 0, 3), probabilistic_sharpe(0.1, 100, 0, 3))
        self.assertGreater(probabilistic_sharpe(0.1, 400, 0, 3), probabilistic_sharpe(0.1, 100, 0, 3))
        self.assertLess(probabilistic_sharpe(0.1, 100, -1.0, 6.0), probabilistic_sharpe(0.1, 100, 0.0, 3.0))

    def test_more_trials_means_a_higher_bar(self):
        self.assertEqual(expected_max_sharpe(1, 0.04), 0.0)
        self.assertAlmostEqual(expected_max_sharpe(2, 1.0), 0.5772156649 * 0.9, delta=0.03)
        self.assertLess(expected_max_sharpe(5, 0.01), expected_max_sharpe(500, 0.01))
        one = deflated_sharpe(0.15, 250, 0, 3, 1, 0.01)
        many = deflated_sharpe(0.15, 250, 0, 3, 200, 0.01)
        self.assertAlmostEqual(one, probabilistic_sharpe(0.15, 250, 0, 3), places=12)
        self.assertLess(many, one)
        self.assertLess(many, 0.95)                                    # a lucky-looking best of 200 is not proof

    def test_invalid_inputs(self):
        for call in (lambda: probabilistic_sharpe(0.1, 1, 0, 3), lambda: expected_max_sharpe(0, 0.1),
                     lambda: expected_max_sharpe(3, -1), lambda: probabilistic_sharpe(5.0, 100, 3.0, 1.0)):
            with self.assertRaises(ValueError):
                call()


if __name__ == '__main__':
    unittest.main()
