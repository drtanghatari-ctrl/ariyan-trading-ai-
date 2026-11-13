"""Load the five-instrument daily set. Missing weekdays are declared closed ONLY if they are known holiday
dates (Dec 24-26, Dec 31-Jan 2, Easter Fri/Mon); any other gap splits the series and the longest run is kept.
Usage: PYTHONPATH=app python research/load_d1.py FILE SYMBOL
"""
import sys
from datetime import date, datetime, timedelta

from ariyan_trading.fx_csv import load_fx_csv


def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


def known_holidays(first, last):
    out = set()
    for y in range(first.year, last.year + 1):
        out |= {date(y, 1, 1), date(y, 1, 2), date(y, 12, 24), date(y, 12, 25), date(y, 12, 26), date(y, 12, 31)}
        e = easter(y)
        out |= {e - timedelta(2), e + timedelta(1)}
    return sorted(out)


def load(path, symbol):
    return load_fx_csv(path, symbol=symbol, source='MT5-D1-EXPORT', timezone_name='UTC',
                       holidays=known_holidays(date(2018, 1, 1), date(2026, 12, 31)))


if __name__ == '__main__':
    ds, rep = load(sys.argv[1], sys.argv[2])
    print(sys.argv[2], len(ds.candles), datetime.utcfromtimestamp(ds.candles[0].timestamp_ms / 1000).date(),
          datetime.utcfromtimestamp(ds.candles[-1].timestamp_ms / 1000).date(), 'runs', len(rep.runs), ds.raw_sha256)
