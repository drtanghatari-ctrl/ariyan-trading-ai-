"""EURUSD daily study: fixed textbook strategies, then walk-forward selection. Offline, deterministic.

Usage:  PYTHONPATH=app python research/eurusd_d1_study.py PATH_TO_MT5_D1_EXPORT.csv OUT.json

PRE-REGISTRATION: every strategy, parameter, cost and window below was written BEFORE any result was
seen and is not changed afterwards. The fixed-parameter table is not tuned. Fifteen strategies are
tested, so a "best of the table" is expected to look good by chance; read the walk-forward result and the
buy-and-hold comparison instead. Costs: a 1.0-pip spread and a swap that is unknown, so two scenarios.
Notional exposure is about 1x equity (margin_fraction 0.01 at a 1% margin rate).
"""
import json
import sys

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.fx_csv import load_fx_csv
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import MarginAssetClass, MarginInstrumentSpec, MarginProduct
from ariyan_trading.strategies import BuyAndHold, Momentum, SmaCross
from ariyan_trading.strategies_extra import (
    BollingerReversion, DonchianBreakout, Ensemble, RsiReversion, TrendFilter,
)
from ariyan_trading.walkforward import WalkForwardConfig, parameter_grid, walk_forward

SPEC = MarginInstrumentSpec(
    identity=InstrumentIdentity('MT5-D1-EXPORT', 'EURUSD'), display_symbol='EURUSD',
    asset_class=MarginAssetClass.FOREX, product=MarginProduct.FX_MARGIN, base_label='EUR',
    quote_currency='USD', contract_size='100000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
    price_step='0.00001', pip_size='0.0001', initial_margin_rate='0.01', maintenance_margin_rate='0.005',
    allows_short=True, financing_reference='STUDY-SWAP-SCENARIO', commission_reference='STUDY-NO-COMMISSION',
    calendar_reference='STUDY-DAILY-WEEKDAYS-V1', timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
    effective_from_ms=0, effective_until_ms=None, source_label='assumed standard FX contract terms',
    observed_at_ms=1)

SCENARIOS = {'no_swap': '0', 'swap_6usd_per_lot_per_day_both_ways': '6'}


def config(swap):
    return BacktestConfig(opening_cash='10000', margin_fraction='0.01', spread='0.00010',
                          financing_long_per_lot_per_bar=swap, financing_short_per_lot_per_bar=swap,
                          periods_per_year=252, financing_basis='ELAPSED')


FIXED = {
    'buy_and_hold': BuyAndHold(),
    'sma_50_200_long_only': SmaCross(50, 200, allow_short=False),
    'sma_50_200_long_short': SmaCross(50, 200, allow_short=True),
    'trend_200_long_only': TrendFilter(200, False),
    'trend_200_long_short': TrendFilter(200, True),
    'momentum_126_long_short': Momentum(126, allow_short=True),
    'donchian_55_20_long_short': DonchianBreakout(55, 20, True),
    'donchian_20_10_long_short': DonchianBreakout(20, 10, True),
    'rsi2_reversion_long_only': RsiReversion(allow_short=False),
    'rsi2_reversion_long_short': RsiReversion(allow_short=True),
    'bollinger_20_2_long_only': BollingerReversion(allow_short=False),
    'bollinger_20_2_long_short': BollingerReversion(allow_short=True),
    'ensemble_trend_donchian_momentum': Ensemble((TrendFilter(200, True), DonchianBreakout(55, 20, True),
                                                  Momentum(126, allow_short=True))),
    'ensemble_trend_donchian_rsi': Ensemble((TrendFilter(200, True), DonchianBreakout(55, 20, True),
                                             RsiReversion(allow_short=True))),
}

FAMILIES = {
    'trend_filter': parameter_grid(TrendFilter, window=[50, 100, 150, 200, 250], allow_short=[False, True]),
    'donchian': parameter_grid(DonchianBreakout, entry_window=[20, 40, 55, 80], exit_window=[10, 20],
                               allow_short=[False, True]),
    'sma_cross': parameter_grid(SmaCross, short_window=[10, 20, 50], long_window=[100, 150, 200],
                                allow_short=[False, True]),
    'rsi_reversion': parameter_grid(RsiReversion, oversold=[5, 10, 15], allow_short=[False, True]),
}


def pick(metrics):
    keys = ('total_return_pct', 'max_drawdown_pct', 'sharpe_annualized', 'trades', 'exposure_pct',
            'spread_cost', 'financing_cost')
    return {k: metrics.get(k) for k in keys}


def main(path, out_path):
    dataset, report = load_fx_csv(path, symbol='EURUSD', source='MT5 MetaQuotes-Demo D1 export')
    first, last, count = report.kept_run
    result = {'data': {'candles': count, 'first_ms': first, 'last_ms': last, 'sha256': report.raw_sha256,
                       'runs': len(report.runs), 'dropped_outside_session': report.dropped_outside_session},
              'fixed_strategies': {}, 'walk_forward': {}}
    for scenario, swap in SCENARIOS.items():
        table = {}
        for name, strategy in FIXED.items():
            table[name] = pick(run_backtest(dataset, SPEC, strategy, config(swap)).metrics)
        result['fixed_strategies'][scenario] = table
    wf_config = WalkForwardConfig(train_bars=756, test_bars=126, objective='sharpe_per_bar', min_train_trades=3)
    everything = tuple(c for family in FAMILIES.values() for c in family)
    groups = dict(FAMILIES, all_families=everything)
    for scenario, swap in SCENARIOS.items():
        result['walk_forward'][scenario] = {}
        for name, candidates in groups.items():
            outcome = walk_forward(dataset, SPEC, candidates, wf_config, config(swap)).to_record()
            result['walk_forward'][scenario][name] = {'candidates': len(candidates),
                                                      'aggregate': outcome['aggregate']}
    with open(out_path, 'w', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
    return result


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
