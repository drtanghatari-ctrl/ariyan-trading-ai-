"""A050 pre-registered broader-universe study. Runs ONCE (the registry blocks a second run).
PYTHONPATH=app:research python research/broader_study.py CLEAN_DIR REGISTRY.jsonl OUT.json
"""
import hashlib
import json
import sys
from datetime import datetime, timezone
from statistics import variance

from load_d1 import load
from ariyan_trading.portfolio import Instrument, PortfolioConfig, aligned, common_calendar, simulate
from ariyan_trading.research_controls import ExperimentRegistry
from ariyan_trading.scorecard import deflated_sharpe, scorecard

B = 1e-4
INSTR = {  # symbol: (one-way cost, financing long, financing short, inverse)   all per unit notional
    'EURUSD': (1.0 * B, 0.986 * B, 0.0, False), 'GBPUSD': (1.0 * B, 0.140 * B, 0.216 * B, False),
    'USDJPY': (1.0 * B, 0.0, 1.910 * B, True), 'AUDUSD': (1.25 * B, 0.0, 0.496 * B, False),
    'USDCAD': (1.0 * B, 0.0, 1.707 * B, True), 'USDCHF': (1.0 * B, 0.0, 1.904 * B, True),
    'NZDUSD': (1.5 * B, 0.909 * B, 0.0, False), 'XAUUSD': (1.5 * B, 2.310 * B, 0.0, False),
    'BTCUSD': (8.0 * B, 6.849 * B, 6.849 * B, False)}
FX8 = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD', 'XAUUSD')
ALL9 = FX8 + ('BTCUSD',)
CANDIDATES = ('mom252', 'sma200', 'mom_ens')
PRIOR_TRIALS = 64 + 3
F_END = datetime(2018, 11, 12, 23, 59, tzinfo=timezone.utc)
HOLDOUT = datetime(2025, 11, 12, tzinfo=timezone.utc)


def ms(dt):
    return int(dt.timestamp() * 1000)


def instruments(symbols):
    return [Instrument(s, INSTR[s][0], 0.0, INSTR[s][3], INSTR[s][1], INSTR[s][2]) for s in symbols]


def year_returns(curve):
    out, last_year, last_eq = {}, None, None
    for t, eq in curve:
        y = datetime.fromtimestamp(t / 1000, timezone.utc).year
        if last_year is None:
            last_year, last_eq = y, eq
        elif y != last_year:
            out[last_year] = round(prev / last_eq - 1, 4)
            last_year, last_eq = y, prev
        prev = eq
    out[last_year] = round(prev / last_eq - 1, 4)
    return out


def run_segment(datasets, symbols, calendar):
    series = {s: aligned(datasets[s], calendar) for s in symbols}
    inst = instruments(symbols)
    res = {}
    for name in CANDIDATES + ('long',):
        base = simulate(series, inst, calendar, name, PortfolioConfig())
        stress = simulate(series, inst, calendar, name, PortfolioConfig(cost_mult=2.0, fin_mult=2.0))
        nofin = simulate(series, inst, calendar, name, PortfolioConfig(fin_mult=0.0))
        total = sum(base.pnl_by_instrument.values())
        res[name] = {
            'card': scorecard(base, 252, bootstrap=500), 'final_equity': base.final_equity,
            'stressed_final_equity': stress.final_equity, 'no_financing_final_equity': nofin.final_equity,
            'halts': base.halts, 'position_changes': base.position_changes, 'costs_paid': base.costs_paid,
            'financing_paid': base.financing_paid, 'pnl_by_instrument': base.pnl_by_instrument,
            'profit_share': {s: (v / total if total > 0 else None) for s, v in base.pnl_by_instrument.items()},
            'by_year': year_returns(base.equity_curve)}
    return res


def rnd(x):
    if isinstance(x, float):
        return round(x, 6)
    if isinstance(x, dict):
        return {str(k): rnd(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v) for v in x]
    return x


def main(data_dir, registry_path, out_path):
    reg = ExperimentRegistry(registry_path)
    if any(r['config'].get('protocol') == 'A050' for r in reg.records()):
        raise SystemExit('The A050 study was already run. A new run needs a new written protocol.')
    datasets, shas = {}, []
    for s in ALL9:
        datasets[s], _ = load('%s/%s_d1.csv' % (data_dir, s.lower() + ('' if s == 'BTCUSD' else '_o')), s)
        shas.append(datasets[s].raw_sha256)
    dataset_id = hashlib.sha256(''.join(sorted(shas)).encode()).hexdigest()
    cal_f = common_calendar([datasets[s] for s in FX8], end_ms=ms(F_END))
    cal_e = common_calendar([datasets[s] for s in ALL9], end_ms=ms(HOLDOUT) - 1)
    seg_f, seg_e = run_segment(datasets, FX8, cal_f), run_segment(datasets, ALL9, cal_e)

    sharpes = [seg_f[n]['card']['sharpe_per_bar'] or 0.0 for n in CANDIDATES]
    best = max(CANDIDATES, key=lambda n: seg_f[n]['card']['sharpe_per_bar'] or -1)
    n_trials = len(CANDIDATES) + PRIOR_TRIALS
    c, f, e = seg_f[best]['card'], seg_f[best], seg_e[best]
    dsr = deflated_sharpe(c['sharpe_per_bar'], c['bars'], c['skewness'], c['kurtosis'], n_trials, variance(sharpes)) \
        if c['sharpe_per_bar'] is not None else None
    positive = [s for s, v in f['pnl_by_instrument'].items() if v > 0]
    shares = [v for v in f['profit_share'].values() if v is not None]
    marks = {
        'F1_net_positive_base_and_stressed': f['final_equity'] > 10_000 and f['stressed_final_equity'] > 10_000,
        'F2_deflated_sharpe_ge_0.95': bool(dsr is not None and dsr >= 0.95),
        'F3_max_drawdown_le_10pct': c['max_drawdown'] <= 0.10,
        'F4_positive_on_5_of_8_none_over_50pct': len(positive) >= 5 and (not shares or max(shares) <= 0.5),
        'F5_at_least_100_position_changes': f['position_changes'] >= 100,
        'F6_beats_always_long_sharpe': (c['sharpe_per_bar'] or -1) > (seg_f['long']['card']['sharpe_per_bar'] or -1),
        'E7_net_positive_base_and_stressed_and_dd_le_10pct': (
            e['final_equity'] > 10_000 and e['stressed_final_equity'] > 10_000 and e['card']['max_drawdown'] <= 0.10)}
    summary = rnd({'best_candidate': best, 'deflated_sharpe_probability': dsr, 'n_trials_used': n_trials, 'marks': marks,
                   'verdict': 'PASS' if all(marks.values()) else 'FAIL',
                   'F_calendar': [cal_f[0], cal_f[-1], len(cal_f)], 'E_calendar': [cal_e[0], cal_e[-1], len(cal_e)],
                   'F': seg_f, 'E': seg_e})
    json.dump(summary, open(out_path, 'w'), indent=1, sort_keys=True)
    for seg, res in (('F', seg_f), ('E', seg_e)):
        for name in CANDIDATES:
            card = res[name]['card']
            reg.log('EXPERIMENT', 'trend_portfolio_litefinance', dataset_id,
                    {'protocol': 'A050', 'segment': seg, 'signal': name, 'n_trials': 1},
                    {'sharpe_per_bar': str(card['sharpe_per_bar']), 'total_return': round(card['total_return'], 4),
                     'max_drawdown': round(card['max_drawdown'], 4),
                     'verdict_for_best': summary['verdict'] if (seg == 'F' and name == best) else None},
                    'Pre-registered A050 candidate; F decides, E is a consistency check.')
    print(json.dumps({k: summary[k] for k in ('best_candidate', 'deflated_sharpe_probability', 'marks', 'verdict')}, indent=1))
    for seg in ('F', 'E'):
        for name in CANDIDATES + ('long',):
            card, r = summary[seg][name]['card'], summary[seg][name]
            print('%s %-7s ret %7.1f%% vol %5.1f%% maxDD %5.1f%% Sharpe %s stressed %7.1f%% nofin %7.1f%% halts %d changes %d' % (
                seg, name, 100 * card['total_return'], 100 * card['volatility'], 100 * card['max_drawdown'],
                round(card['sharpe_annualised'], 2) if card['sharpe_annualised'] is not None else None,
                100 * (r['stressed_final_equity'] / 10_000 - 1), 100 * (r['no_financing_final_equity'] / 10_000 - 1),
                r['halts'], r['position_changes']))


if __name__ == '__main__':
    main(*sys.argv[1:4])
