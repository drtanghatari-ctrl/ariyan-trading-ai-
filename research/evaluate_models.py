"""Apply the A047 pre-registered pass marks. Usage: PYTHONPATH=app:research python research/evaluate_models.py
DATA_DIR FORECAST_DIR MODEL_NAME OUT.json   (data files named eurusd_d1.csv etc., forecasts_<file-model>_<SYMBOL>.csv)
"""
import glob
import json
import os
import sys

from load_d1 import load
from ariyan_trading.forecast_signals import load_forecasts
from ariyan_trading.forecast_study import study

END_MS = 1762819200000 + 86_400_000  # last decision 2025-11-11 -> realised 2025-11-12 at most; holdout starts 2025-11-12


def main(data_dir, forecast_dir, model_name, out):
    entries, shas = [], {}
    for path in sorted(glob.glob(os.path.join(forecast_dir, 'forecasts_*_*.csv'))):
        symbol = os.path.basename(path)[:-4].split('_')[-1]
        book = load_forecasts(path)
        if not book.rows(symbol, model_name, 1):
            continue
        dataset, _ = load(os.path.join(data_dir, '%s_d1.csv' % symbol.lower()), symbol)
        entries.append({'symbol': symbol, 'dataset': dataset, 'book': book, 'model': model_name})
        shas[symbol] = book.sha256
    result = study(entries, end_ms=1762819200000)       # decisions up to 2025-11-11, outcomes inside development
    result['forecast_sha256'] = shas
    json.dump(result, open(out, 'w'), indent=1, sort_keys=True)
    print(json.dumps(result['pooled'], indent=1), result['marks'], result['verdict'])


if __name__ == '__main__':
    main(*sys.argv[1:5])
