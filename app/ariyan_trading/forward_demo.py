"""A042 forward PAPER run on real MT5 data. Sends NO orders to MT5; the terminal is read-only here.

    set MT5_PASSWORD=your-demo-password
    python -m ariyan_trading.forward_demo --login 115560232 --server MetaQuotes-Demo --symbol EURUSD ^
        --timeframe H1 --strategy sma:10:30 --lots 0.01 --log forward_log.jsonl

Stop with Ctrl+C. Use --max-steps 1 for a single dry check. Strategies: hold, sma:SHORT:LONG,
momentum:BARS, trend:WINDOW, donchian:ENTRY:EXIT, rsi, boll (append :short to allow short positions);
join several with + for a majority vote, e.g. trend:200+donchian:20:10+boll.
"""
import argparse
import getpass
import json
import os
import time

from .forward import ForwardPaperRunner
from .mt5_adapter import MT5DemoBroker, MT5Error, load_mt5
from .strategies import BuyAndHold, Momentum, SmaCross
from .strategies_extra import (
    BollingerReversion, DonchianBreakout, Ensemble, RsiReversion, TrendFilter,
)


def _parse_one(text):
    parts = text.split(':')
    kind, args = parts[0], parts[1:]
    allow_short = bool(args) and args[-1] == 'short'
    if allow_short:
        args = args[:-1]
    try:
        if kind == 'hold' and not args:
            return BuyAndHold()
        if kind == 'sma' and len(args) == 2:
            return SmaCross(int(args[0]), int(args[1]), allow_short=allow_short)
        if kind == 'momentum' and len(args) == 1:
            return Momentum(int(args[0]), allow_short=allow_short)
        if kind == 'trend' and len(args) == 1:
            return TrendFilter(int(args[0]), allow_short=allow_short)
        if kind == 'donchian' and len(args) == 2:
            return DonchianBreakout(int(args[0]), int(args[1]), allow_short=allow_short)
        if kind == 'rsi' and not args:
            return RsiReversion(allow_short=allow_short)
        if kind == 'boll' and not args:
            return BollingerReversion(allow_short=allow_short)
    except ValueError as exc:
        raise ValueError('Bad strategy %r: %s' % (text, exc)) from exc
    raise ValueError('Unknown strategy %r' % text)


def parse_strategy(text):
    """hold, sma:10:30, momentum:20, trend:200, donchian:20:10, rsi, boll; add :short to allow shorts.
    Join several with + for a majority-vote ensemble, e.g. trend:200+donchian:20:10+boll"""
    if '+' in text:
        return Ensemble(tuple(_parse_one(part) for part in text.split('+')))
    return _parse_one(text)


def main(argv=None, mt5_module=None, password=None, sleep=time.sleep):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--login', type=int, required=True)
    parser.add_argument('--server', required=True)
    parser.add_argument('--path')
    parser.add_argument('--symbol', required=True, help='Canonical symbol, e.g. EURUSD')
    parser.add_argument('--broker-symbol', help='Name at your broker if different, e.g. EURUSD_o')
    parser.add_argument('--timeframe', default='H1')
    parser.add_argument('--strategy', default='sma:10:30')
    parser.add_argument('--lots', default='0.01')
    parser.add_argument('--stop-distance', help='Stop-loss distance in price units, e.g. 0.00500')
    parser.add_argument('--poll-seconds', type=int, default=30)
    parser.add_argument('--max-steps', type=int)
    parser.add_argument('--log', default='forward_log.jsonl')
    args = parser.parse_args(argv)
    secret = password or os.environ.get('MT5_PASSWORD') or getpass.getpass('MT5 demo password: ')
    try:
        strategy = parse_strategy(args.strategy)
        mapping = {args.symbol: args.broker_symbol} if args.broker_symbol else {}
        broker = MT5DemoBroker(mt5_module or load_mt5(), magic=7_700_002, symbol_map=mapping,
                               expected_server=args.server)
        broker.connect(args.login, secret, args.server, args.path)
        try:
            runner = ForwardPaperRunner(broker, strategy, args.symbol, args.timeframe, args.lots,
                                        'FWD-%d' % int(time.time()), args.log,
                                        stop_distance=args.stop_distance)
            print(json.dumps({'paper_only': True, 'orders_sent_to_mt5': 0, 'log': args.log,
                              'strategy': strategy.describe(), 'timeframe': args.timeframe}, indent=2))
            runner.run(args.poll_seconds, args.max_steps, sleep)
        finally:
            broker.close()
    except KeyboardInterrupt:
        print('Stopped.')
        return 0
    except (MT5Error, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, indent=2))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
