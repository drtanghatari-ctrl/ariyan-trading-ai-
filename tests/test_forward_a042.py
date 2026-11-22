"""A042 forward paper runner against a FAKE terminal. Synthetic prices only."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from decimal import Decimal as D
from types import SimpleNamespace as NS

try:
    from test_mt5_adapter_a040 import FakeMT5, PASSWORD
except ImportError:  # run as tests.test_forward_a042 from the repository root
    from tests.test_mt5_adapter_a040 import FakeMT5, PASSWORD

from ariyan_trading import forward_demo
from ariyan_trading.forward import ForwardPaperRunner
from ariyan_trading.mt5_adapter import MT5DemoBroker, MT5Error
from ariyan_trading.strategies import SmaCross

H1 = 3600


class FakeFeed(FakeMT5):
    TIMEFRAME_H1 = 16385

    def __init__(self, closes, **kwargs):
        super().__init__(**kwargs)
        info = self.symbols['EURUSD.r']
        info.trade_contract_size, info.point, info.digits = 100000.0, 0.00001, 5
        self.series = []
        for close in closes:
            self.add_bar(close)
        self.add_bar(closes[-1])   # the still-forming bar, which must never be returned

    def add_bar(self, close):
        index = len(self.series)
        close = float(close)
        self.series.append({'time': 1_700_000_000 + index * H1, 'open': close, 'high': close + 0.001,
                            'low': close - 0.001, 'close': close, 'tick_volume': 10})

    def copy_rates_from_pos(self, symbol, timeframe, start, count):
        if symbol not in self.symbols or timeframe != self.TIMEFRAME_H1:
            return None
        end = len(self.series) - start
        return self.series[max(0, end - count):end]


def connect(mt5):
    broker = MT5DemoBroker(mt5, magic=7700002, symbol_map={'EURUSD': 'EURUSD.r'})
    broker.connect(123, PASSWORD, 'Demo-Server')
    return broker


class ForwardA042Tests(unittest.TestCase):
    def logfile(self):
        handle = tempfile.NamedTemporaryFile(suffix='.jsonl', delete=False)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def records(self, path):
        with open(path, encoding='utf-8') as stream:
            return [json.loads(line) for line in stream]

    def test_closed_candles_exclude_the_forming_bar_and_are_ordered(self):
        mt5 = FakeFeed([1.10, 1.09, 1.08, 1.07])
        candles = connect(mt5).closed_candles('EURUSD', 'H1', 3)
        self.assertEqual([c.close for c in candles], [D('1.09'), D('1.08'), D('1.07')])
        self.assertEqual(len(mt5.series), 5)                       # five bars exist, one is forming
        self.assertTrue(all(type(c.close) is D for c in candles))
        with self.assertRaises(ValueError):
            connect(mt5).closed_candles('EURUSD', 'H7', 3)
        mt5.series.clear()
        with self.assertRaises(MT5Error):
            connect(mt5).closed_candles('EURUSD', 'H1', 3)

    def test_symbol_terms_are_read_from_the_terminal(self):
        terms = connect(FakeFeed([1.1, 1.1, 1.1])).symbol_terms('EURUSD')
        self.assertEqual((terms['contract_size'], terms['point'], terms['digits'], terms['lot_step']),
                         (D('100000.0'), D('0.00001'), 5, D('0.01')))

    def test_warm_up_does_not_trade_then_new_candles_do_and_mt5_gets_no_orders(self):
        mt5 = FakeFeed([1.10, 1.09, 1.08])
        path = self.logfile()
        runner = ForwardPaperRunner(connect(mt5), SmaCross(2, 3, allow_short=False), 'EURUSD', 'H1',
                                    '0.01', 'FWD-T1', path)
        self.assertEqual(runner.step(), [])                          # warm-up: history only
        self.assertEqual(runner.paper.positions(), ())
        mt5.series.pop()                                              # drop the forming bar, add a closed one
        mt5.add_bar(1.12)
        mt5.add_bar(1.12)                                             # new forming bar
        mt5.ticks['EURUSD.r'] = NS(bid=1.12, ask=1.1202, time_msc=6000)
        new = runner.step()
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]['actions'][0]['status'], 'FILLED')
        self.assertEqual(len(runner.paper.positions()), 1)           # paper long opened at the ask
        self.assertEqual(runner.paper.positions()[0].entry_price, D('1.1202'))
        mt5.series.pop()
        mt5.add_bar(1.00)
        mt5.add_bar(1.00)
        mt5.ticks['EURUSD.r'] = NS(bid=1.0, ask=1.0002, time_msc=7000)
        runner.step()
        self.assertEqual(runner.paper.positions(), ())               # signal flipped to flat: closed
        self.assertEqual(runner.step(), [])                          # no new candle, no new action
        self.assertEqual(mt5.sent, [])                               # NOTHING was ever sent to MT5
        events = [r['event'] for r in self.records(path)]
        self.assertEqual(events, ['START', 'CANDLE', 'CANDLE'])
        self.assertTrue(self.records(path)[0]['paper_only'])

    def test_unsupported_symbol_and_bad_timeframe_are_refused(self):
        mt5 = FakeFeed([1.1, 1.1, 1.1])
        mt5.symbols['USDJPY'] = mt5.symbols['EURUSD.r']
        mt5.ticks['USDJPY'] = mt5.ticks['EURUSD.r']
        broker = MT5DemoBroker(mt5, magic=7700002)
        broker.connect(123, PASSWORD, 'Demo-Server')
        with self.assertRaisesRegex(ValueError, 'USD-quoted'):
            ForwardPaperRunner(broker, SmaCross(2, 3), 'USDJPY', 'H1', '0.01', 'FWD-T2', self.logfile())
        with self.assertRaises(ValueError):
            ForwardPaperRunner(connect(mt5), SmaCross(2, 3), 'EURUSD', 'H9', '0.01', 'FWD-T3', self.logfile())

    def test_run_stops_after_repeated_terminal_errors(self):
        mt5 = FakeFeed([1.1, 1.1, 1.1])
        path = self.logfile()
        runner = ForwardPaperRunner(connect(mt5), SmaCross(2, 3), 'EURUSD', 'H1', '0.01', 'FWD-T4', path)
        mt5.series.clear()
        with self.assertRaises(MT5Error):
            runner.run(poll_seconds=0, max_errors=3, sleep=lambda s: None)
        events = [r['event'] for r in self.records(path)]
        self.assertEqual(events.count('ERROR'), 3)
        self.assertEqual(events[-1], 'STOPPED')

    def test_float_noise_in_terminal_quotes_and_candles_is_cleaned(self):
        # Regression: a real run stopped with "Too many decimal places" on a noisy double.
        mt5 = FakeFeed([1.10, 1.09, 1.08])
        mt5.ticks['EURUSD.r'] = NS(bid=1.1057700000000002, ask=1.10579, time_msc=5000)
        broker = connect(mt5)
        quote = broker.quote('EURUSD')
        self.assertEqual((quote.bid, quote.ask), (D('1.10577'), D('1.10579')))
        runner = ForwardPaperRunner(broker, SmaCross(2, 3), 'EURUSD', 'H1', '0.01', 'FWD-T5', self.logfile())
        mt5.ticks['EURUSD.r'] = NS(bid=1.1058100000000001, ask=1.1058300000000001, time_msc=6000)
        runner.step()
        mt5.account.balance = 10000.300000000001
        self.assertEqual(broker.account().balance, D('10000.3'))

    def test_cli_accepts_the_new_strategies_and_ensembles(self):
        for text in ('trend:200', 'donchian:20:10:short', 'rsi', 'boll:short', 'trend:200+donchian:20:10+boll'):
            self.assertTrue(forward_demo.parse_strategy(text).lookback >= 1, text)
        with self.assertRaises(ValueError):
            forward_demo.parse_strategy('donchian:20')

    def test_cli_single_step_and_bad_strategy(self):
        mt5, path, out = FakeFeed([1.1, 1.1, 1.1]), self.logfile(), io.StringIO()
        with contextlib.redirect_stdout(out):
            code = forward_demo.main(['--login', '123', '--server', 'Demo-Server', '--symbol', 'EURUSD',
                                      '--broker-symbol', 'EURUSD.r', '--strategy', 'sma:2:3', '--max-steps', '1',
                                      '--log', path], mt5_module=mt5, password=PASSWORD, sleep=lambda s: None)
        self.assertEqual(code, 0)
        summary = json.loads(out.getvalue())
        self.assertEqual((summary['paper_only'], summary['orders_sent_to_mt5']), (True, 0))
        self.assertNotIn(PASSWORD, out.getvalue())
        self.assertEqual(mt5.sent, [])
        self.assertEqual(mt5.shutdowns, 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = forward_demo.main(['--login', '123', '--server', 'Demo-Server', '--symbol', 'EURUSD',
                                      '--broker-symbol', 'EURUSD.r', '--strategy', 'nonsense', '--log', path],
                                     mt5_module=FakeFeed([1.1, 1.1, 1.1]), password=PASSWORD)
        self.assertEqual(code, 1)

    def test_parse_strategy(self):
        self.assertEqual(forward_demo.parse_strategy('sma:5:20:short'), SmaCross(5, 20, allow_short=True))
        self.assertEqual(forward_demo.parse_strategy('sma:5:20'), SmaCross(5, 20, allow_short=False))
        with self.assertRaises(ValueError):
            forward_demo.parse_strategy('sma:20:5')


if __name__ == '__main__':
    unittest.main()
