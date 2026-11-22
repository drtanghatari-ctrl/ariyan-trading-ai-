"""Run one model over all five instruments, one after the other (laptop). Resumable: just run it again.

  python research\run_forecast_study.py DATA_FOLDER OUT_FOLDER timesfm
  python research\run_forecast_study.py DATA_FOLDER OUT_FOLDER kronos

DATA_FOLDER holds the five MT5 Daily exports (names like EURUSD_Daily_*.csv); if a symbol has several files,
the one with the latest end date in its name is used. Output: OUT_FOLDER\forecasts_<model>_<SYMBOL>.csv.
Settings are FIXED by the pre-registered protocol (A047): decisions 2023-01-01..2025-11-11, context 400,
horizon 1, Kronos 5 draws. Do not change them.
"""
import glob
import os
import subprocess
import sys

SYMBOLS = ('EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'BTCUSD')
HERE = os.path.dirname(os.path.abspath(__file__))


def newest(folder, symbol):
    files = sorted(glob.glob(os.path.join(folder, '%s_Daily_*.csv' % symbol)),
                   key=lambda f: os.path.basename(f).split('_')[-1])
    return files[-1] if files else None


def main(data, out, model):
    if model not in ('kronos', 'timesfm'):
        raise SystemExit('model must be kronos or timesfm')
    os.makedirs(out, exist_ok=True)
    missing = [s for s in SYMBOLS if not newest(data, s)]
    if missing:
        raise SystemExit('No Daily CSV found for: %s' % ', '.join(missing))
    for symbol in SYMBOLS:
        target = os.path.join(out, 'forecasts_%s_%s.csv' % (model, symbol))
        command = [sys.executable, os.path.join(HERE, 'make_forecasts.py'), newest(data, symbol), symbol, target,
                   '--model', model, '--start', '2023-01-01', '--end', '2025-11-11', '--context', '400',
                   '--draws', '5', '--kronos-repo', os.path.join(os.path.dirname(HERE), 'Kronos')]
        print('==== %s %s' % (model, symbol), flush=True)
        if subprocess.call(command) != 0:
            raise SystemExit('Stopped at %s. Fix the error and run the same command again.' % symbol)
    print('ALL DONE. Send the forecasts_%s_*.csv files.' % model)


if __name__ == '__main__':
    main(*sys.argv[1:4])
