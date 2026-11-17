"""A049 read-only MT5 data tool: broker costs and Daily history for many symbols in one command.

It attaches to the MT5 terminal that is ALREADY running and logged in (no password, no login call) and only
reads symbol information and history. It never sends, modifies or closes an order. Works with an investor
(read-only) login. Run it once per broker account, because swaps, spreads and available history differ.

  python -m ariyan_trading.mt5_data costs  --symbols EURUSD,GBPUSD,XAUUSD --out costs_server.json
  python -m ariyan_trading.mt5_data find   --pattern "*OIL*,*GER*,*NAS*"
  python -m ariyan_trading.mt5_data export --symbols EURUSD,GBPUSD --folder daily_export

Spread and swap are reported as points and as basis points of price, because basis points are what the
portfolio simulator needs. Only swap modes whose unit is certain are converted; others are left as None.
"""
import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

from .mt5_adapter import load_mt5

SWAP_POINTS, SWAP_CCY_SYMBOL, SWAP_CCY_MARGIN, SWAP_INTEREST_CURRENT, SWAP_INTEREST_OPEN = 1, 2, 3, 5, 6
D1_BARS = 3200          # about twelve years of weekday bars; the terminal returns what it has


def _round(value, digits=6):
    return None if value is None else round(float(value), digits)


def swap_bp_per_day(mode, swap, point, contract_size, price):
    """Swap as basis points of notional per day, or None when the unit is not certain."""
    if not price or price <= 0:
        return None
    if mode == SWAP_POINTS:
        return swap * point / price * 1e4
    if mode in (SWAP_INTEREST_CURRENT, SWAP_INTEREST_OPEN):   # annual percent
        return swap / 365.0 * 100
    if mode in (SWAP_CCY_SYMBOL, SWAP_CCY_MARGIN) and contract_size:
        return swap / (contract_size * price) * 1e4 if mode == SWAP_CCY_SYMBOL else None
    return None


def symbol_costs(mt5, name):
    mt5.symbol_select(name, True)
    info = mt5.symbol_info(name)
    if info is None:
        return {'symbol': name, 'found': False}
    tick = mt5.symbol_info_tick(name)
    mid = (tick.bid + tick.ask) / 2 if tick is not None and tick.bid and tick.ask else None
    rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 1, 250)
    spreads = [int(r['spread']) for r in rates] if rates is not None and len(rates) else []
    median_spread = statistics.median(spreads) if spreads else None
    point, contract = float(info.point), float(info.trade_contract_size)
    mode = int(info.swap_mode)
    return {
        'symbol': name, 'found': True, 'path': info.path, 'description': info.description,
        'currency_base': info.currency_base, 'currency_profit': info.currency_profit,
        'currency_margin': info.currency_margin, 'digits': int(info.digits), 'point': point,
        'contract_size': contract, 'volume_min': _round(info.volume_min), 'volume_step': _round(info.volume_step),
        'volume_max': _round(info.volume_max), 'mid_price': mid,
        'spread_now_points': int(info.spread), 'spread_floating': bool(info.spread_float),
        'spread_median_daily_points_250d': median_spread,
        'spread_bp_now': _round(info.spread * point / mid * 1e4) if mid else None,
        'spread_bp_median_250d': _round(median_spread * point / mid * 1e4) if mid and median_spread is not None else None,
        'swap_mode': mode, 'swap_long': _round(info.swap_long), 'swap_short': _round(info.swap_short),
        'swap_rollover3days': int(info.swap_rollover3days),
        'swap_long_bp_per_day': _round(swap_bp_per_day(mode, float(info.swap_long), point, contract, mid)),
        'swap_short_bp_per_day': _round(swap_bp_per_day(mode, float(info.swap_short), point, contract, mid)),
        'margin_initial': _round(info.margin_initial), 'trade_calc_mode': int(info.trade_calc_mode),
        'trade_mode': int(info.trade_mode)}


def collect_costs(mt5, symbols):
    account = mt5.account_info()
    return {'server': getattr(account, 'server', None) if account else None,
            'account_trade_mode': getattr(account, 'trade_mode', None) if account else None,
            'collected_utc': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'note': 'read-only; swap_*_bp_per_day is None when the swap unit is not certain; spread bp is the FULL spread',
            'symbols': [symbol_costs(mt5, s) for s in symbols]}


def export_daily(mt5, name, folder, bars=D1_BARS):
    """Write NAME_Daily_<first>_<last>.csv in the MT5 'Export Bars' format. Returns a summary dict."""
    mt5.symbol_select(name, True)
    info = mt5.symbol_info(name)
    if info is None:
        return {'symbol': name, 'ok': False, 'reason': 'unknown symbol'}
    rates = mt5.copy_rates_from_pos(name, mt5.TIMEFRAME_D1, 0, bars)
    if rates is None or len(rates) < 100:
        return {'symbol': name, 'ok': False, 'reason': 'only %d bars returned: open a Daily chart of %s, scroll '
                'far left to load history, then run again' % (0 if rates is None else len(rates), name)}
    digits = int(info.digits)
    stamp = lambda t: datetime.fromtimestamp(int(t), timezone.utc)
    first, last = stamp(rates[0]['time']), stamp(rates[-1]['time'])
    path = Path(folder) / ('%s_Daily_%s_%s.csv' % (name, first.strftime('%Y%m%d0000'), last.strftime('%Y%m%d0000')))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='') as out:
        out.write('<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n')
        for r in rates:
            out.write('%s\t%.*f\t%.*f\t%.*f\t%.*f\t%d\t%d\t%d\n' % (
                stamp(r['time']).strftime('%Y.%m.%d'), digits, r['open'], digits, r['high'], digits, r['low'],
                digits, r['close'], int(r['tick_volume']), int(r['real_volume']), int(r['spread'])))
    days = sorted({stamp(r['time']).date() for r in rates})
    biggest_gap = max(((b - a).days for a, b in zip(days, days[1:])), default=0)
    return {'symbol': name, 'ok': True, 'file': str(path), 'bars': len(rates), 'first': first.date().isoformat(),
            'last': last.date().isoformat(), 'largest_gap_days': biggest_gap}


def find_symbols(mt5, patterns):
    found = {}
    for pattern in patterns:
        for s in mt5.symbols_get(group=pattern) or ():
            found[s.name] = s.description
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only MT5 costs and Daily history')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('costs', 'export'):
        p = sub.add_parser(name)
        p.add_argument('--symbols', required=True, help='comma separated broker symbol names')
        p.add_argument('--path', default=None, help='terminal64.exe path if MT5 is not found automatically')
        if name == 'costs':
            p.add_argument('--out', default=None)
        else:
            p.add_argument('--folder', required=True)
    f = sub.add_parser('find')
    f.add_argument('--pattern', required=True, help='comma separated wildcards, for example *OIL*,*GER*')
    f.add_argument('--path', default=None)
    args = parser.parse_args(argv)
    mt5 = load_mt5()
    if not (mt5.initialize(path=args.path) if args.path else mt5.initialize()):
        print(json.dumps({'ok': False, 'error': 'Could not attach to MT5: %r' % (mt5.last_error(),)}))
        return 2
    try:
        if args.command == 'find':
            print(json.dumps(find_symbols(mt5, [p.strip() for p in args.pattern.split(',') if p.strip()]), indent=1))
            return 0
        symbols = [s.strip() for s in args.symbols.split(',') if s.strip()]
        if args.command == 'costs':
            result = collect_costs(mt5, symbols)
            text = json.dumps(result, indent=1)
            if args.out:
                Path(args.out).write_text(text, encoding='utf-8')
            print(text)
        else:
            summaries = [export_daily(mt5, s, args.folder) for s in symbols]
            print(json.dumps(summaries, indent=1))
        return 0
    finally:
        mt5.shutdown()


if __name__ == '__main__':
    sys.exit(main())
