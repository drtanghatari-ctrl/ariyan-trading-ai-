"""A045 research controls: experiment registry and a once-only locked final test.

Purpose: make it hard to fool ourselves. Offline, deterministic, no network.

- `ExperimentRegistry` is an append-only JSON-lines log where every record carries the hash of the
  previous one, so editing, deleting or reordering any record is detected on the next read. Every
  experiment is logged, including failures; the trial count it keeps feeds the Deflated Sharpe Ratio.
- `development_dataset` cuts the final period off a dataset. `log_development_experiment` refuses to
  log an experiment whose data reaches into that locked period.
- `final_holdout_test` runs ONE frozen strategy on the locked period exactly once per dataset and
  period. A second attempt, with any strategy, raises. A holdout that was already looked at before it
  was locked (a DISCLOSURE record) is marked contaminated in the result.

This does not stop a determined person from reading the data. It makes accidental or habitual peeking
visible and countable, which is the realistic goal.
"""
import hashlib
import json
import os
import time

from .session_candles import slice_dataset
from .walkforward import WalkForwardConfig, walk_forward

GENESIS = '0' * 64
DAY_MS = 86_400_000
KINDS = ('EXPERIMENT', 'FINAL_HOLDOUT', 'LEGACY_FULL_SAMPLE', 'DISCLOSURE')


class RegistryError(ValueError):
    pass


class HoldoutAlreadyUsed(RegistryError):
    pass


def _hash(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


class ExperimentRegistry:
    def __init__(self, path, clock_ms=None):
        self._path = path
        self._clock = clock_ms or (lambda: int(time.time() * 1000))

    def records(self):
        if not os.path.exists(self._path):
            return []
        out, previous = [], GENESIS
        with open(self._path, encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                try:
                    record = json.loads(line)
                    body = {k: v for k, v in record.items() if k != 'hash'}
                    valid = (record.get('seq') == number and record.get('prev_hash') == previous
                             and _hash(body) == record.get('hash'))
                except (ValueError, AttributeError):
                    valid = False
                if not valid:
                    raise RegistryError('Registry is corrupt or was edited at record %d' % number)
                previous = record['hash']
                out.append(record)
        return out

    def log(self, kind, family, dataset_sha256, config, results=None, note=''):
        if kind not in KINDS:
            raise RegistryError('kind must be one of %s' % (KINDS,))
        if not family or not isinstance(config, dict):
            raise RegistryError('family and a config dict are required')
        records = self.records()
        body = {'seq': len(records) + 1, 'logged_ms': self._clock(), 'kind': kind, 'family': family,
                'dataset_sha256': dataset_sha256, 'config': config, 'results': results, 'note': note,
                'prev_hash': records[-1]['hash'] if records else GENESIS}
        record = dict(body, hash=_hash(body))
        with open(self._path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')
        return record

    def trials(self, family=None):
        """Total strategies/parameter sets tried (each record's config 'n_trials', default 1)."""
        return sum(int(r['config'].get('n_trials', 1)) for r in self.records()
                   if r['kind'] in ('EXPERIMENT', 'LEGACY_FULL_SAMPLE') and (family is None or r['family'] == family))

    def trial_sharpes(self, family=None):
        """Per-bar Sharpe ratios of logged experiments (for the trial-variance input of the DSR)."""
        return [float(r['results']['sharpe_per_bar']) for r in self.records()
                if r['kind'] == 'EXPERIMENT' and (family is None or r['family'] == family)
                and isinstance(r.get('results'), dict) and r['results'].get('sharpe_per_bar') is not None]


def holdout_start_index(dataset, days=365):
    """Index of the first candle in the final `days` days of the dataset."""
    cutoff = dataset.candles[-1].timestamp_ms - days * DAY_MS
    for index, candle in enumerate(dataset.candles):
        if candle.timestamp_ms >= cutoff:
            if index < 2:
                raise ValueError('Holdout would leave no development data')
            return index
    raise ValueError('Holdout period not found')


def development_dataset(dataset, start_index):
    """The dataset without the locked final period."""
    return slice_dataset(dataset, 0, start_index)


def log_development_experiment(registry, dataset, holdout_start_ms, family, config, results, note=''):
    if dataset.candles[-1].timestamp_ms >= holdout_start_ms:
        raise RegistryError('Dataset reaches into the locked holdout; use development_dataset()')
    config = dict(config, symbol=dataset.symbol, last_candle_ms=dataset.candles[-1].timestamp_ms,
                  holdout_start_ms=holdout_start_ms)
    return registry.log('EXPERIMENT', family, dataset.raw_sha256, config, results, note)


def final_holdout_test(registry, dataset, start_index, strategy, spec, config, label, family, conversion=()):
    """Run ONE frozen strategy on candles[start_index:], once per dataset and period."""
    if type(start_index) is not int or not 2 <= start_index < len(dataset.candles) - 1:
        raise ValueError('start_index must leave development and holdout data')
    start_ms = dataset.candles[start_index].timestamp_ms
    contaminated = False
    for record in registry.records():
        same = (record['dataset_sha256'] == dataset.raw_sha256
                and record['config'].get('symbol') == dataset.symbol)
        if same and record['kind'] == 'FINAL_HOLDOUT' and record['config'].get('holdout_start_ms') == start_ms:
            raise HoldoutAlreadyUsed('The final test for %s from %d was already used (record %d)'
                                     % (dataset.symbol, start_ms, record['seq']))
        if same and record['kind'] in ('DISCLOSURE', 'LEGACY_FULL_SAMPLE') and record['config'].get('contaminated_holdout'):
            contaminated = True
    wf = WalkForwardConfig(train_bars=start_index, test_bars=len(dataset.candles) - start_index,
                           objective='total_return_pct', min_train_trades=0)
    result = walk_forward(dataset, spec, (strategy,), wf, config, conversion)
    fold = result.folds[0]
    registry.log('FINAL_HOLDOUT', family, dataset.raw_sha256,
                 {'symbol': dataset.symbol, 'holdout_start_ms': start_ms, 'label': label,
                  'strategy': strategy.describe(), 'n_trials': 1, 'contaminated': contaminated},
                 {'test_return_pct': fold.test_return_pct, 'benchmark_return_pct': fold.benchmark_return_pct,
                  'test_max_drawdown_pct': fold.test_max_drawdown_pct, 'test_trades': fold.test_trades,
                  'test_ruined': fold.test_ruined})
    return result, contaminated
