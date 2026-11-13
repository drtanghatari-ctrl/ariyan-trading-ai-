"""Record the locked 12-month holdout of each daily dataset in the registry (DISCLOSURE-free, nothing is evaluated).
Usage: PYTHONPATH=app python research/lock_holdouts.py DATA_DIR REGISTRY.jsonl
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load_d1 import load  # noqa: E402
from ariyan_trading.research_controls import ExperimentRegistry, holdout_start_index  # noqa: E402

SYMBOLS = ('EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD')


def main(data_dir, registry_path):
    reg = ExperimentRegistry(registry_path)
    for symbol in SYMBOLS:
        ds, _ = load('%s/%s_d1.csv' % (data_dir, symbol.lower()), symbol)
        index = holdout_start_index(ds)
        start = ds.candles[index].timestamp_ms
        if any(r['kind'] == 'DISCLOSURE' and r['dataset_sha256'] == ds.raw_sha256 and r['config'].get('holdout_start_ms') == start
               for r in reg.records()):
            print(symbol, 'already locked')
            continue
        contaminated = symbol == 'EURUSD'
        reg.log('DISCLOSURE', 'holdout_lock', ds.raw_sha256,
                {'symbol': symbol, 'holdout_start_ms': start, 'holdout_bars': len(ds.candles) - index,
                 'development_bars': index, 'contaminated_holdout': contaminated, 'evaluated_before_lock': contaminated},
                None, 'Locked final 12 months. No strategy has been run on this data.' if not contaminated
                else 'EURUSD holdout was already seen in A044; lock is nominal.')
        print(symbol, 'locked from', datetime.fromtimestamp(start / 1000, timezone.utc).date(),
              'dev bars', index, 'holdout bars', len(ds.candles) - index)


if __name__ == '__main__':
    main(*sys.argv[1:3])
