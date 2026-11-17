"""A047 pre-registered test of forecasting models across instruments. Offline, deterministic.

The pass marks below were written BEFORE the multi-instrument results were seen and are not changed after.
A model is useful as a signal only if it meets ALL FOUR marks on development data. Failing means it is dropped
from the strategist; trying other settings needs a new written protocol and counts as new trials.

  1. Mean rank IC across instruments >= 0.03, its 90% block-bootstrap interval above 0, and rank IC > 0 on at
     least 60% of instruments.
  2. Pooled directional accuracy >= 52%.
  3. Mean absolute error lower than a zero ("no change") forecast on at least 60% of instruments.
  4. Pooled 10-90% interval coverage between 70% and 90% (target 80%).
"""
import math
import random

from .forecast_signals import _correlation, _ranks, scored_rows

PASS_MARKS = {'min_mean_rank_ic': 0.03, 'min_pooled_direction': 0.52, 'min_instrument_share': 0.6,
              'coverage_low': 0.70, 'coverage_high': 0.90, 'confidence': 0.9}


def _stats(rows):
    pred, real = [r[0] for r in rows], [r[1] for r in rows]
    signed = [(p > 0) == (r > 0) for p, r in zip(pred, real) if p != 0 and r != 0]
    ic = _correlation(_ranks(pred), _ranks(real))
    return {'n': len(rows), 'hits': sum(signed), 'signed': len(signed), 'rank_ic': ic,
            'mae_model': sum(abs(r - p) for p, r in zip(pred, real)) / len(rows),
            'mae_zero': sum(abs(r) for r in real) / len(rows), 'covered': sum(r[2] for r in rows)}


def study(entries, end_ms=None, bootstrap=500, block=20, seed=1, marks=PASS_MARKS):
    """entries: dicts with symbol, dataset, book, model. Returns per-instrument table, pooled results, verdict."""
    if not entries:
        raise ValueError('No entries')
    rows = {}
    for e in entries:
        data = scored_rows(e['book'], e['dataset'], e['symbol'], e['model'], end_ms=end_ms)
        if len(data) < 100:
            raise ValueError('%s: only %d scored forecasts; at least 100 are needed' % (e['symbol'], len(data)))
        rows[e['symbol']] = data
    per = {s: _stats(r) for s, r in rows.items()}
    ics = [v['rank_ic'] for v in per.values() if v['rank_ic'] is not None]
    mean_ic = sum(ics) / len(ics) if ics else None
    hits, signed = sum(v['hits'] for v in per.values()), sum(v['signed'] for v in per.values())
    total, covered = sum(v['n'] for v in per.values()), sum(v['covered'] for v in per.values())
    rng = random.Random(seed)
    boot_ic = []
    for _ in range(bootstrap):
        values = []
        for data in rows.values():
            n, sample = len(data), []
            while len(sample) < n:
                start = rng.randrange(n)
                sample.extend(data[start:start + block])
            ic = _correlation(_ranks([r[0] for r in sample[:n]]), _ranks([r[1] for r in sample[:n]]))
            if ic is not None:
                values.append(ic)
        if values:
            boot_ic.append(sum(values) / len(values))
    boot_ic.sort()
    tail = (1 - marks['confidence']) / 2
    ci = [boot_ic[int(tail * (len(boot_ic) - 1))], boot_ic[int((1 - tail) * (len(boot_ic) - 1))]] if boot_ic else None
    k = len(per)
    need = math.ceil(marks['min_instrument_share'] * k)
    pooled = {'instruments': k, 'mean_rank_ic': mean_ic, 'rank_ic_interval': ci,
              'instruments_positive_ic': sum(1 for x in ics if x > 0),
              'pooled_direction': hits / signed if signed else None,
              'instruments_beating_zero_forecast': sum(1 for v in per.values() if v['mae_model'] < v['mae_zero']),
              'pooled_coverage': covered / total, 'forecasts': total}
    results = {
        'mark1_rank_ic': bool(mean_ic is not None and ci and mean_ic >= marks['min_mean_rank_ic'] and ci[0] > 0
                              and pooled['instruments_positive_ic'] >= need),
        'mark2_direction': bool(pooled['pooled_direction'] is not None
                                and pooled['pooled_direction'] >= marks['min_pooled_direction']),
        'mark3_beats_zero_forecast': pooled['instruments_beating_zero_forecast'] >= need,
        'mark4_calibration': marks['coverage_low'] <= pooled['pooled_coverage'] <= marks['coverage_high'],
    }
    table = {s: {'n': v['n'], 'rank_ic': v['rank_ic'],
                 'direction': v['hits'] / v['signed'] if v['signed'] else None,
                 'mae_model': v['mae_model'], 'mae_zero': v['mae_zero'], 'coverage': v['covered'] / v['n']}
             for s, v in per.items()}
    return {'per_instrument': table, 'pooled': pooled, 'marks': results, 'verdict': 'PASS' if all(results.values()) else 'FAIL'}
