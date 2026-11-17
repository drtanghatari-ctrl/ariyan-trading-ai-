"""Lock the final holdout of the nine LiteFinance Daily datasets (A050). The start is the explicit date
2025-11-12, the same lock already recorded for the MetaQuotes feed (it is slightly longer than 12 months).
Nothing is evaluated. Usage: PYTHONPATH=app python research/lock_holdouts_lf.py CLEAN_DIR REGISTRY.jsonl
"""
import sys
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit('/', 1)[0])
from load_d1 import load  # noqa: E402
from ariyan_trading.research_controls import ExperimentRegistry  # noqa: E402

SYMBOLS = ('EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD', 'XAUUSD', 'BTCUSD')
START = datetime(2025, 11, 12, tzinfo=timezone.utc)


def main(data_dir, registry_path):
    reg = ExperimentRegistry(registry_path)
    start = int(START.timestamp() * 1000)
    for symbol in SYMBOLS:
        name = symbol.lower() + ('' if symbol == 'BTCUSD' else '_o')
        ds, rep = load('%s/%s_d1.csv' % (data_dir, name), symbol)
        index = next(i for i, c in enumerate(ds.candles) if c.timestamp_ms >= start)
        if any(r['kind'] == 'DISCLOSURE' and r['dataset_sha256'] == ds.raw_sha256 for r in reg.records()):
            print(symbol, 'already locked')
            continue
        reg.log('DISCLOSURE', 'holdout_lock_litefinance', ds.raw_sha256,
                {'symbol': symbol, 'holdout_start_ms': start, 'holdout_bars': len(ds.candles) - index,
                 'development_bars': index, 'first_bar_ms': ds.candles[0].timestamp_ms,
                 'contaminated_holdout': False, 'evaluated_before_lock': False,
                 'data_note': 'Sunday stub bars merged into Monday (research/prepare_lf.py)'},
                None, 'Locked final holdout from 2025-11-12. No strategy has been run on this data; only '
                      'data-quality statistics (bar counts, gaps, daily volatility, largest moves) were viewed.')
        print(symbol, 'locked; dev bars', index, 'holdout bars', len(ds.candles) - index,
              'first', datetime.fromtimestamp(ds.candles[0].timestamp_ms / 1000, timezone.utc).date())


if __name__ == '__main__':
    main(*sys.argv[1:3])
