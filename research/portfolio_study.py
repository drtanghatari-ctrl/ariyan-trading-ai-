"""A048 pre-registered portfolio study on DEVELOPMENT data. Runs ONCE (the registry blocks a second run).

PYTHONPATH=app:research python research/portfolio_study.py DATA_DIR REGISTRY.jsonl OUT.json
"""
import json
import math
import sys
from statistics import variance

from load_d1 import load
from ariyan_trading.portfolio import Instrument, PortfolioConfig, aligned, common_calendar, simulate
from ariyan_trading.research_controls import ExperimentRegistry, holdout_start_index
from ariyan_trading.scorecard import deflated_sharpe, scorecard

SYMBOLS = ('EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD')
INSTRUMENTS = [Instrument('EURUSD', 0.0001, 0.00005), Instrument('GBPUSD', 0.0001, 0.00005),
               Instrument('USDJPY', 0.0001, 0.00005, inverse=True), Instrument('XAUUSD', 0.0002, 0.00005),
               Instrument('BTCUSD', 0.0008, 0.0002)]
CANDIDATES = ('mom252', 'sma200', 'mom_ens')
PRIOR_TRIALS = 64          # A044 EURUSD study (conservative inclusion)


def round_floats(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {k: round_floats(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [round_floats(v) for v in x]
    return x


def main(data_dir, registry_path, out_path):
    reg = ExperimentRegistry(registry_path)
    if any(r['config'].get('protocol') == 'A048' for r in reg.records()):
        raise SystemExit('The A048 study was already run. A new run needs a new written protocol.')
    datasets = {s: load('%s/%s_d1.csv' % (data_dir, s.lower()), s)[0] for s in SYMBOLS}
    holdout_ms = min(d.candles[holdout_start_index(d)].timestamp_ms for d in datasets.values())
    calendar = common_calendar(list(datasets.values()), end_ms=holdout_ms - 1)
    series = {s: aligned(d, calendar) for s, d in datasets.items()}
    results = {}
    for name in CANDIDATES + ('long',):
        base = simulate(series, INSTRUMENTS, calendar, name, PortfolioConfig())
        stress = simulate(series, INSTRUMENTS, calendar, name, PortfolioConfig(cost_mult=2.0, fin_mult=2.0))
        card = scorecard(base, 252, bootstrap=500)
        total = sum(base.pnl_by_instrument.values())
        results[name] = {
            'card': card, 'final_equity': base.final_equity, 'stressed_final_equity': stress.final_equity,
            'stressed_return': stress.final_equity / 10_000 - 1, 'halts': base.halts, 'halted_bars': base.halted_bars,
            'position_changes': base.position_changes, 'costs_paid': base.costs_paid, 'financing_paid': base.financing_paid,
            'pnl_by_instrument': base.pnl_by_instrument,
            'profit_share': {s: (v / total if total > 0 else None) for s, v in base.pnl_by_instrument.items()}}
    sharpes = [results[n]['card']['sharpe_per_bar'] or 0.0 for n in CANDIDATES]
    trial_var = variance(sharpes)
    n_trials = len(CANDIDATES) + PRIOR_TRIALS
    best = max(CANDIDATES, key=lambda n: results[n]['card']['sharpe_per_bar'] or -1)
    c = results[best]['card']
    dsr = deflated_sharpe(c['sharpe_per_bar'], c['bars'], c['skewness'], c['kurtosis'], n_trials, trial_var) \
        if c['sharpe_per_bar'] is not None else None
    r = results[best]
    positive = [s for s, v in r['pnl_by_instrument'].items() if v > 0]
    shares = [v for v in r['profit_share'].values() if v is not None]
    marks = {
        '1_net_positive_base_and_stressed': r['final_equity'] > 10_000 and r['stressed_final_equity'] > 10_000,
        '2_deflated_sharpe_ge_0.95': bool(dsr is not None and dsr >= 0.95),
        '3_max_drawdown_le_10pct_from_all_time_high': c['max_drawdown'] <= 0.10,
        '4_positive_on_3_of_5_and_none_over_50pct': len(positive) >= 3 and (not shares or max(shares) <= 0.5),
        '5_at_least_100_position_changes': r['position_changes'] >= 100,
        '6_beats_always_long_sharpe': (c['sharpe_per_bar'] or -1) > (results['long']['card']['sharpe_per_bar'] or -1),
    }
    summary = {'best_candidate': best, 'deflated_sharpe_probability': dsr, 'n_trials_used': n_trials,
               'trial_sharpe_variance': trial_var, 'marks': marks, 'verdict': 'PASS' if all(marks.values()) else 'FAIL',
               'calendar': [calendar[0], calendar[-1], len(calendar)], 'results': results}
    summary = round_floats(summary)
    json.dump(summary, open(out_path, 'w'), indent=1, sort_keys=True)
    for name in CANDIDATES:
        card = results[name]['card']
        reg.log('EXPERIMENT', 'trend_portfolio', 'five-instrument-d1', {'protocol': 'A048', 'signal': name, 'n_trials': 1},
                {'sharpe_per_bar': str(card['sharpe_per_bar']), 'total_return': round(card['total_return'], 4),
                 'max_drawdown': round(card['max_drawdown'], 4), 'stressed_return': round(results[name]['stressed_return'], 4),
                 'verdict_for_best': summary['verdict'] if name == best else None},
                'Pre-registered A048 candidate, development data only.')
    print(json.dumps({k: summary[k] for k in ('best_candidate', 'deflated_sharpe_probability', 'marks', 'verdict')}, indent=1))
    for name in CANDIDATES + ('long',):
        card, r = results[name]['card'], results[name]
        print('%-8s return %6.1f%%  ann %s  vol %5.1f%%  maxDD %5.1f%%  Sharpe %s  stressed %6.1f%%  halts %d  changes %d' % (
            name, 100 * card['total_return'], None if card['annualised_return'] is None else round(100 * card['annualised_return'], 1),
            100 * card['volatility'], 100 * card['max_drawdown'], round(card['sharpe_annualised'], 2) if card['sharpe_annualised'] is not None else None,
            100 * r['stressed_return'], r['halts'], r['position_changes']))


if __name__ == '__main__':
    main(*sys.argv[1:4])
