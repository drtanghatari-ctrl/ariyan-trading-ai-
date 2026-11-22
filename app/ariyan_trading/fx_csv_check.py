"""A041 read-only check of a downloaded candle CSV. Prints what the importer accepted and dropped.

    python -m ariyan_trading.fx_csv_check C:\\path\\EURUSD.csv --symbol EURUSD
    python -m ariyan_trading.fx_csv_check file.csv --symbol EURUSD --utc-offset-minutes 120   (MT5 server GMT+2)
"""
import argparse
import json
from datetime import datetime, timezone

from .fx_csv import load_fx_csv


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('path')
    parser.add_argument('--symbol', required=True)
    parser.add_argument('--utc-offset-minutes', type=int)
    parser.add_argument('--timezone-name')
    parser.add_argument('--skip-bad-rows', action='store_true')
    args = parser.parse_args(argv)
    try:
        dataset, report = load_fx_csv(
            args.path, symbol=args.symbol, source='local file ' + args.path.replace('\\', '/').split('/')[-1],
            utc_offset_minutes=args.utc_offset_minutes, timezone_name=args.timezone_name,
            on_bad_row='skip' if args.skip_bad_rows else 'raise')
    except (ValueError, OSError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, indent=2))
        return 1
    first, last, count = report.kept_run
    print(json.dumps({
        'ok': True, 'symbol': dataset.symbol, 'bar_seconds': report.interval_ms // 1000,
        'rows_read': report.rows_read, 'candles_kept': count, 'first': _iso(first), 'last': _iso(last),
        'skipped_bad_rows': len(report.skipped_rows), 'dropped_outside_session': report.dropped_outside_session,
        'gap_free_runs': len(report.runs), 'older_candles_cut_for_limit': report.truncated_to_recent,
        'sha256': report.raw_sha256}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
