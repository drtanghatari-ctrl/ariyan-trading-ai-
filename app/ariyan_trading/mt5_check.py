"""A040 read-only MetaTrader 5 connection check. It never places an order.

Run on Windows with the MT5 terminal installed:

    set MT5_PASSWORD=your-demo-password
    python -m ariyan_trading.mt5_check --login 12345678 --server Your-Broker-Demo --symbol EURUSD

The password is read from MT5_PASSWORD or a hidden prompt, never from the command
line. The check fails unless the terminal is logged in to a DEMO account.
"""
import argparse
import getpass
import json
import os

from .mt5_adapter import MT5DemoBroker, MT5Error, load_mt5


def main(argv=None, mt5_module=None, password=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--login', type=int, required=True)
    parser.add_argument('--server', required=True)
    parser.add_argument('--path', help='Optional path to terminal64.exe')
    parser.add_argument('--symbol', help='Optional symbol to read one quote for')
    parser.add_argument('--symbol-map', action='append', default=[], metavar='CANONICAL=BROKER',
                        help='Broker symbol name, e.g. EURUSD=EURUSD_o (repeatable)')
    args = parser.parse_args(argv)
    symbol_map = {}
    for item in args.symbol_map:
        canonical, separator, broker_name = item.partition('=')
        if not separator or not canonical or not broker_name:
            parser.error('--symbol-map must look like EURUSD=EURUSD_o')
        symbol_map[canonical] = broker_name
    secret = password or os.environ.get('MT5_PASSWORD') or getpass.getpass('MT5 demo password: ')
    try:
        mt5 = mt5_module or load_mt5()
        broker = MT5DemoBroker(mt5, magic=7_700_001, symbol_map=symbol_map, expected_server=args.server)
        broker.connect(args.login, secret, args.server, args.path)
        try:
            account = broker.account()
            report = {'connected': True, 'mode': account.mode.value, 'currency': account.currency,
                      'margin_mode': broker.account_type(),
                      'balance': str(account.balance), 'equity': str(account.equity),
                      'open_positions_by_this_system': len(broker.positions())}
            if args.symbol:
                quote = broker.quote(args.symbol)
                report['quote'] = {'symbol': args.symbol, 'bid': str(quote.bid), 'ask': str(quote.ask),
                                   'time_ms': quote.time_ms}
        finally:
            broker.close()
    except MT5Error as exc:
        print(json.dumps({'connected': False, 'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
