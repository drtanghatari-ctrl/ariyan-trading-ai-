"""A038 walk-forward validation: choose on past data, judge on unseen data.

For each fold the best candidate strategy is selected using ONLY the training
window, then run on the following test window it has never seen. Parameter
choices therefore cannot be tuned on the results being reported. The aggregate
covers out-of-sample windows only, beside a buy-and-hold benchmark over the same
windows and the in-sample results that exposed any overfitting.

Research evidence only: it neither authorizes trading nor proves an edge. Trying
many candidates still inflates the chance that one looks good out of sample by
luck; `candidates_per_fold` is reported so that multiple testing stays visible.
"""
from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from .backtest import BacktestConfig, run_backtest
from .market_data import CandleDataset
from .session_candles import SessionCandleDataset, slice_dataset
from .strategies import BuyAndHold, Strategy

VERSION = 'ARIYAN-A038-WALK-FORWARD-V1'
CONTEXT = Context(prec=50, rounding=ROUND_HALF_EVEN)
SIX = Decimal('0.000001')
HUNDRED = Decimal(100)
OBJECTIVES = ('total_return_pct', 'sharpe_per_bar', 'return_over_drawdown')
MAX_CANDIDATES = 1000
MAX_FOLDS = 10000


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int
    test_bars: int
    step_bars: int | None = None      # default: test_bars (non-overlapping test windows)
    anchored: bool = False            # True: training always starts at the first bar and grows
    objective: str = 'total_return_pct'
    min_train_trades: int = 1         # candidates with fewer training trades are not eligible

    def __post_init__(self):
        for name, low in (('train_bars', 2), ('test_bars', 2)):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= 10_000_000:
                raise ValueError(name + ' must be an integer >= %d' % low)
        if self.step_bars is not None and (type(self.step_bars) is not int or self.step_bars < 1):
            raise ValueError('step_bars must be a positive integer or None')
        if type(self.anchored) is not bool:
            raise ValueError('anchored must be a boolean')
        if self.objective not in OBJECTIVES:
            raise ValueError('objective must be one of %s' % (OBJECTIVES,))
        if type(self.min_train_trades) is not int or self.min_train_trades < 0:
            raise ValueError('min_train_trades must be a non-negative integer')

    @property
    def step(self):
        return self.step_bars or self.test_bars


@dataclass(frozen=True)
class Fold:
    index: int
    train_first_ms: int
    train_last_ms: int
    test_first_ms: int
    test_last_ms: int
    selected: dict | None
    selected_index: int | None
    train_objective: str | None
    train_return_pct: str | None
    test_return_pct: str
    test_max_drawdown_pct: str
    test_trades: int
    test_ruined: bool
    benchmark_return_pct: str
    note: str

    def to_record(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class WalkForwardResult:
    provenance: dict
    folds: tuple
    aggregate: dict

    def to_record(self):
        return {'version': VERSION, 'investment_evidence': False,
                'executable_support_established': False, 'provenance': self.provenance,
                'aggregate': self.aggregate, 'folds': [f.to_record() for f in self.folds]}


def parameter_grid(factory, **choices):
    """Build candidates from every combination of the given parameter lists.

    parameter_grid(SmaCross, short_window=[3, 5], long_window=[10, 20]) skips
    combinations the strategy itself rejects (for example short >= long).
    """
    import itertools
    names = sorted(choices)
    for name in names:
        if not choices[name] or type(choices[name]) not in (list, tuple):
            raise ValueError('Each parameter needs a non-empty list: ' + name)
    out = []
    for values in itertools.product(*(choices[n] for n in names)):
        try:
            out.append(factory(**dict(zip(names, values))))
        except ValueError:
            continue
    if not out:
        raise ValueError('No valid parameter combination')
    return tuple(out)


def _text(value):
    return str(value.quantize(SIX))


def _objective(metrics, objective):
    if objective == 'sharpe_per_bar':
        return None if metrics['sharpe_per_bar'] is None else Decimal(metrics['sharpe_per_bar'])
    total = Decimal(metrics['total_return_pct'])
    if objective == 'total_return_pct':
        return total
    drawdown = Decimal(metrics['max_drawdown_pct'])
    return total / drawdown if drawdown > 0 else total


def walk_forward(dataset, spec, candidates, wf_config, config=None, conversion=()):
    if type(dataset) not in (CandleDataset, SessionCandleDataset):
        raise ValueError('A validated candle dataset is required')
    if type(wf_config) is not WalkForwardConfig:
        raise ValueError('A WalkForwardConfig is required')
    if (type(candidates) is not tuple or not 1 <= len(candidates) <= MAX_CANDIDATES
            or any(not isinstance(c, Strategy) for c in candidates)):
        raise ValueError('Candidates must be a tuple of 1..%d Strategy objects' % MAX_CANDIDATES)
    config = BacktestConfig() if config is None else config
    longest = max(c.lookback for c in candidates)
    if wf_config.train_bars <= longest + 1:
        raise ValueError('train_bars must exceed the longest strategy lookback by at least 2')
    count = len(dataset.candles)
    starts = list(range(0, count - wf_config.train_bars - wf_config.test_bars + 1, wf_config.step))
    if not starts:
        raise ValueError('Dataset is too short for one train+test fold')
    if len(starts) > MAX_FOLDS:
        raise ValueError('Too many folds; increase step_bars')
    candles = dataset.candles
    folds = []
    with localcontext(CONTEXT):
        for number, start in enumerate(starts):
            train_start = 0 if wf_config.anchored else start
            train_end = start + wf_config.train_bars
            test_end = train_end + wf_config.test_bars
            train = slice_dataset(dataset, train_start, train_end)
            best, best_score, best_return = None, None, None
            for index, strategy in enumerate(candidates):
                if strategy.lookback >= len(train.candles):
                    continue
                result = run_backtest(train, spec, strategy, config, conversion)
                if result.metrics['trades'] < wf_config.min_train_trades:
                    continue
                score = _objective(result.metrics, wf_config.objective)
                if score is not None and (best_score is None or score > best_score):
                    best, best_score, best_return = index, score, result.metrics['total_return_pct']
            chosen = None if best is None else candidates[best]
            # Warm-up bars precede the test window so the first decision lands at test start.
            benchmark = _run_window(dataset, spec, BuyAndHold(), config, conversion, train_end, test_end)
            if chosen is None:
                folds.append(Fold(number, candles[train_start].timestamp_ms, candles[train_end - 1].timestamp_ms,
                                  candles[train_end].timestamp_ms, candles[test_end - 1].timestamp_ms,
                                  None, None, None, None, '0.000000', '0.000000', 0, False,
                                  benchmark.metrics['total_return_pct'],
                                  'No eligible candidate in training window; stayed flat.'))
                continue
            test = _run_window(dataset, spec, chosen, config, conversion, train_end, test_end)
            folds.append(Fold(number, candles[train_start].timestamp_ms, candles[train_end - 1].timestamp_ms,
                              candles[train_end].timestamp_ms, candles[test_end - 1].timestamp_ms,
                              chosen.describe(), best, _text(best_score), best_return,
                              test.metrics['total_return_pct'], test.metrics['max_drawdown_pct'],
                              test.metrics['trades'], test.metrics['ruined'],
                              benchmark.metrics['total_return_pct'], ''))
        aggregate = _aggregate(folds, len(candidates))
    provenance = {
        'dataset_symbol': dataset.symbol, 'dataset_sha256': dataset.raw_sha256,
        'dataset_source': dataset.source, 'bars': count, 'instrument_fingerprint': spec.fingerprint(),
        'candidates': [c.describe() for c in candidates],
        'walk_forward': {'train_bars': wf_config.train_bars, 'test_bars': wf_config.test_bars,
                         'step_bars': wf_config.step, 'anchored': wf_config.anchored,
                         'objective': wf_config.objective, 'min_train_trades': wf_config.min_train_trades},
        'backtest_config': {k: getattr(config, k) for k in config.__dataclass_fields__},
        'note': ('Test-window results are out of sample for the candidate choice only; the data '
                 'range, candidate list and objective were still chosen by a person who may have '
                 'seen this history.')}
    return WalkForwardResult(provenance, tuple(folds), aggregate)


def _run_window(dataset, spec, strategy, config, conversion, test_start, test_end):
    first = max(0, test_start - strategy.lookback)
    window = slice_dataset(dataset, first, test_end)
    return run_backtest(window, spec, strategy, config, conversion)


def _aggregate(folds, candidate_count):
    def compound(values):
        growth = Decimal(1)
        for value in values:
            growth *= 1 + max(Decimal(value), -HUNDRED) / HUNDRED
        return (growth - 1) * HUNDRED

    selected = [f for f in folds if f.selected is not None]
    test = [f.test_return_pct for f in folds]
    bench = [f.benchmark_return_pct for f in folds]
    count = len(folds)
    profitable = sum(1 for f in folds if Decimal(f.test_return_pct) > 0)
    distinct = {repr(sorted(f.selected['params'].items())) + f.selected['name'] for f in selected}
    mean = lambda values: sum((Decimal(v) for v in values), Decimal(0)) / len(values) if values else None
    train_mean = mean([f.train_return_pct for f in selected])
    test_mean = mean(test)
    out_test_selected = mean([f.test_return_pct for f in selected])
    return {
        'folds': count, 'folds_with_selection': len(selected), 'candidates_per_fold': candidate_count,
        'distinct_selected_candidates': len(distinct),
        'compounded_oos_return_pct': _text(compound(test)),
        'compounded_benchmark_return_pct': _text(compound(bench)),
        'excess_over_benchmark_pct': _text(compound(test) - compound(bench)),
        'mean_oos_return_pct': _text(test_mean),
        'mean_in_sample_return_pct': None if train_mean is None else _text(train_mean),
        'in_sample_minus_oos_pct': (None if train_mean is None or out_test_selected is None
                                    else _text(train_mean - out_test_selected)),
        'profitable_folds': profitable, 'profitable_fold_pct': _text(Decimal(profitable) / count * HUNDRED),
        'worst_fold_return_pct': _text(min(Decimal(v) for v in test)),
        'worst_fold_drawdown_pct': _text(max(Decimal(f.test_max_drawdown_pct) for f in folds)),
        'oos_trades': sum(f.test_trades for f in folds),
        'ruined_folds': sum(1 for f in folds if f.test_ruined),
    }
