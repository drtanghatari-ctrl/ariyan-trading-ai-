"""Clean a LiteFinance Daily export: merge short Sunday stub bars into the following Monday bar (open of the
stub, extreme high/low, Monday's close, summed volumes). Deterministic; changes no other row.
Usage: python research/prepare_lf.py IN.csv OUT.csv"""
import sys
from datetime import datetime, timedelta


def prepare(lines):
    head, rows = lines[0], [l.rstrip('\n').split('\t') for l in lines[1:] if l.strip()]
    out, pending = [], None
    for r in rows:
        day = datetime.strptime(r[0], '%Y.%m.%d').date()
        if day.weekday() >= 5:
            pending = r if pending is None else _merge(pending, r)
            continue
        if pending is not None:
            nxt = day
            if (nxt - datetime.strptime(pending[0], '%Y.%m.%d').date()) <= timedelta(2):
                r = _merge(pending, r, keep_date=r[0])
            else:
                out.append(pending)
            pending = None
        out.append(r)
    return head, out


def _merge(a, b, keep_date=None):
    """a = earlier stub, b = later bar. Columns: date, open, high, low, close, tickvol, vol, spread."""
    return [keep_date or a[0], a[1], max(a[2], b[2], key=float), min(a[3], b[3], key=float), b[4],
            str(int(a[5]) + int(b[5])), str(int(a[6]) + int(b[6])), b[7]]


if __name__ == '__main__':
    head, out = prepare(open(sys.argv[1]).readlines())
    with open(sys.argv[2], 'w', newline='') as f:
        f.write(head)
        for r in out:
            f.write('\t'.join(r) + '\n')
    print(len(out), 'rows')
