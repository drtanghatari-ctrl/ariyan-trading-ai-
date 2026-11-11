"""Tests run against a fake terminal; no MetaTrader 5 installation or network is used."""
import contextlib
import io
import json
import sys
import unittest
from decimal import Decimal as D
from types import SimpleNamespace as NS
from unittest import mock

from ariyan_trading import mt5_check
from ariyan_trading.execution import (
    BrokerMode, GuardedBroker, OrderRequest, OrderSide, RiskLimits,
)
from ariyan_trading.mt5_adapter import MT5DemoBroker, MT5Error, load_mt5

BUY, SELL = OrderSide.BUY, OrderSide.SELL
PASSWORD = 'S3cret-demo-pass'


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO, ACCOUNT_TRADE_MODE_CONTEST, ACCOUNT_TRADE_MODE_REAL = 0, 1, 2
    TRADE_ACTION_DEAL, ORDER_TYPE_BUY, ORDER_TYPE_SELL, ORDER_TIME_GTC = 1, 0, 1, 0
    ORDER_FILLING_FOK, ORDER_FILLING_IOC, ORDER_FILLING_RETURN = 0, 1, 2
    SYMBOL_FILLING_FOK, SYMBOL_FILLING_IOC = 1, 2
    POSITION_TYPE_BUY, POSITION_TYPE_SELL = 0, 1
    TRADE_RETCODE_DONE, TRADE_RETCODE_REJECT, TRADE_RETCODE_NO_MONEY = 10009, 10006, 10019
    TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_REQUOTE, TRADE_RETCODE_MARKET_CLOSED = 10012, 10004, 10018

    def __init__(self, trade_mode=0, server='Demo-Server', filling=3):
        self.account = NS(trade_mode=trade_mode, server=server, trade_allowed=True, currency='USD',
                          balance=10000.0, equity=10000.0, margin=0.0, margin_free=10000.0, login=123)
        self.symbols = {'EURUSD.r': NS(volume_min=0.01, volume_max=100.0, volume_step=0.01,
                                       filling_mode=filling)}
        self.ticks = {'EURUSD.r': NS(bid=1.1, ask=1.1002, time_msc=5000)}
        self.positions, self.sent, self.init_ok = [], [], True
        self.shutdowns, self.init_kwargs, self.next_retcode, self.send_none = 0, None, 10009, False
        self.ticket = 1000

    def initialize(self, **kwargs):
        self.init_kwargs = dict(kwargs)
        return self.init_ok

    def shutdown(self):
        self.shutdowns += 1

    def last_error(self):
        return (-1, 'fake error')

    def account_info(self):
        return self.account

    def symbol_info(self, symbol):
        return self.symbols.get(symbol)

    def symbol_select(self, symbol, enable):
        return symbol in self.symbols

    def symbol_info_tick(self, symbol):
        return self.ticks.get(symbol)

    def positions_get(self, **kwargs):
        return tuple(self.positions)

    def order_send(self, request):
        self.sent.append(dict(request))
        if self.send_none:
            return None
        if self.next_retcode != self.TRADE_RETCODE_DONE:
            return NS(retcode=self.next_retcode, comment='fake refusal', order=0, price=0.0, volume=0.0)
        if 'position' in request:
            self.positions = [p for p in self.positions if p.ticket != request['position']]
            return NS(retcode=10009, comment='Done', order=request['position'], price=request['price'],
                      volume=request['volume'])
        self.ticket += 1
        self.positions.append(NS(
            ticket=self.ticket, time_msc=6000, type=request['type'], volume=request['volume'],
            price_open=request['price'], sl=request['sl'], tp=request['tp'], profit=12.5,
            symbol=request['symbol'], comment=request['comment'], magic=request['magic']))
        return NS(retcode=10009, comment='Done', order=self.ticket, price=request['price'],
                  volume=request['volume'])


def connected(mt5=None, **kwargs):
    mt5 = mt5 or FakeMT5()
    broker = MT5DemoBroker(mt5, magic=555, symbol_map={'EURUSD': 'EURUSD.r'}, **kwargs)
    broker.connect(123, PASSWORD, 'Demo-Server')
    return broker, mt5


def order(cid='ORD1', side=BUY, lots='0.10', **kwargs):
    return OrderRequest(cid, 'EURUSD', side, lots, **kwargs)


class MT5DemoBrokerA040Tests(unittest.TestCase):
    def test_connect_verifies_a_demo_account_and_keeps_no_secrets(self):
        broker, mt5 = connected()
        self.assertIs(broker.mode, BrokerMode.DEMO)
        self.assertEqual(mt5.init_kwargs, {'login': 123, 'password': PASSWORD, 'server': 'Demo-Server'})
        account = broker.account()
        self.assertEqual((account.currency, account.balance, account.equity, account.free_margin),
                         ('USD', D(10000), D(10000), D(10000)))
        self.assertNotIn(PASSWORD, repr(vars(broker)))
        self.assertNotIn(PASSWORD, repr(broker.account()))

    def test_real_contest_and_other_accounts_are_refused(self):
        for mode in (2, 1):
            mt5 = FakeMT5(trade_mode=mode)
            broker = MT5DemoBroker(mt5, magic=555)
            with self.assertRaisesRegex(MT5Error, 'not a DEMO'):
                broker.connect(123, PASSWORD, 'Demo-Server')
            self.assertEqual(mt5.shutdowns, 1)
            with self.assertRaises(MT5Error):
                broker.account()  # never became usable
        wrong = FakeMT5(server='Live-Server')
        with self.assertRaisesRegex(MT5Error, 'unexpected server'):
            MT5DemoBroker(wrong, magic=555, expected_server='Demo-Server').connect(123, PASSWORD, 'Live-Server')
        disabled = FakeMT5()
        disabled.account.trade_allowed = False
        with self.assertRaisesRegex(MT5Error, 'disabled'):
            MT5DemoBroker(disabled, magic=555).connect(123, PASSWORD, 'Demo-Server')

    def test_connection_failures(self):
        failing = FakeMT5()
        failing.init_ok = False
        with self.assertRaisesRegex(MT5Error, 'initialize failed'):
            MT5DemoBroker(failing, magic=555).connect(123, PASSWORD, 'Demo-Server')
        silent = FakeMT5()
        silent.account_info = lambda: None
        with self.assertRaises(MT5Error):
            MT5DemoBroker(silent, magic=555).connect(123, PASSWORD, 'Demo-Server')
        for args in ((0, 'p', 's'), (1, '', 's'), (1, 'p', ''), ('1', 'p', 's')):
            with self.assertRaises(ValueError):
                MT5DemoBroker(FakeMT5(), magic=555).connect(*args)

    def test_a_terminal_switched_to_real_is_detected_before_every_action(self):
        broker, mt5 = connected()
        mt5.account.trade_mode = mt5.ACCOUNT_TRADE_MODE_REAL
        for call in (broker.account, broker.positions, lambda: broker.quote('EURUSD'),
                     lambda: broker.submit(order()), lambda: broker.close_position('1', 'C1')):
            with self.assertRaises(MT5Error):
                call()
        self.assertEqual(mt5.sent, [])

    def test_buy_request_is_built_correctly(self):
        broker, mt5 = connected()
        result = broker.submit(order(stop_loss='1.09500', take_profit='1.11000'))
        self.assertEqual((result.status, result.position_id, result.price, result.lots),
                         ('FILLED', '1001', D('1.1002'), D('0.10')))
        sent, = mt5.sent
        self.assertEqual(sent, {
            'action': 1, 'symbol': 'EURUSD.r', 'volume': 0.1, 'type': 0, 'price': 1.1002,
            'sl': 1.095, 'tp': 1.11, 'deviation': 10, 'magic': 555, 'comment': 'ORD1',
            'type_time': 0, 'type_filling': 0})  # FOK is preferred when the symbol allows it

    def test_sell_uses_the_bid_and_filling_mode_follows_the_symbol(self):
        for flags, expected in ((1, 0), (2, 1), (3, 0), (0, 2)):
            broker, mt5 = connected(FakeMT5(filling=flags))
            broker.submit(order(side=SELL))
            self.assertEqual((mt5.sent[0]['type'], mt5.sent[0]['price'], mt5.sent[0]['type_filling']),
                             (1, 1.1, expected), flags)

    def test_positions_are_converted_and_filtered_by_magic(self):
        broker, mt5 = connected()
        broker.submit(order(stop_loss='1.09500'))
        mt5.positions.append(NS(ticket=9, time_msc=1, type=1, volume=5.0, price_open=1.2, sl=0.0, tp=0.0,
                                profit=-1.0, symbol='EURUSD.r', comment='manual', magic=0))
        positions = broker.positions()
        self.assertEqual(len(positions), 1)
        p = positions[0]
        self.assertEqual((p.position_id, p.symbol, p.side, p.lots, p.entry_price, p.stop_loss, p.take_profit,
                          p.unrealized_pnl), ('1001', 'EURUSD', BUY, D('0.1'), D('1.1002'), D('1.095'), None,
                                              D('12.5')))
        self.assertEqual(broker.quote('EURUSD').ask, D('1.1002'))

    def test_orders_are_idempotent(self):
        broker, mt5 = connected()
        first = broker.submit(order())
        self.assertEqual(first, broker.submit(order()))
        self.assertEqual(len(mt5.sent), 1)
        self.assertEqual(broker.submit(order(lots='0.2')).reason, 'DUPLICATE_ID_CONFLICT')

    def test_restart_finds_an_already_open_order_by_its_comment(self):
        broker, mt5 = connected()
        broker.submit(order('RUN-O1'))
        fresh = MT5DemoBroker(mt5, magic=555, symbol_map={'EURUSD': 'EURUSD.r'})
        fresh.connect(123, PASSWORD, 'Demo-Server')
        again = fresh.submit(order('RUN-O1'))
        self.assertEqual((again.status, again.reason, again.position_id), ('FILLED', 'ALREADY_OPEN', '1001'))
        self.assertEqual(len(mt5.sent), 1)

    def test_rejections_that_never_reach_the_terminal(self):
        broker, mt5 = connected()
        for request, reason in ((order('A', lots='0.001'), 'LOTS_OUTSIDE_SYMBOL_TERMS'),
                                (order('B', lots='100.01'), 'LOTS_OUTSIDE_SYMBOL_TERMS'),
                                (OrderRequest('C', 'XXXXXX', BUY, '1'), 'UNKNOWN_SYMBOL')):
            result = broker.submit(request)
            self.assertEqual((result.status, result.reason), ('REJECTED', reason))
        self.assertEqual(mt5.sent, [])

    def test_outcome_classification(self):
        broker, mt5 = connected()
        mt5.next_retcode = mt5.TRADE_RETCODE_NO_MONEY
        refused = broker.submit(order('R1'))
        self.assertEqual((refused.status, refused.position_id), ('REJECTED', None))
        self.assertIn('RETCODE_10019', refused.reason)
        mt5.next_retcode = mt5.TRADE_RETCODE_TIMEOUT      # ambiguous: the order may have been placed
        with self.assertRaisesRegex(MT5Error, 'UNKNOWN'):
            broker.submit(order('R2'))
        mt5.next_retcode, mt5.send_none = mt5.TRADE_RETCODE_DONE, True
        with self.assertRaisesRegex(MT5Error, 'UNKNOWN'):
            broker.submit(order('R3'))

    def test_guard_turns_an_unknown_outcome_into_a_halt(self):
        broker, mt5 = connected()
        guard = GuardedBroker(broker, RiskLimits(
            allowed_symbols=frozenset({'EURUSD'}), max_lots_per_order=D(1), max_open_positions=2,
            max_total_lots=D(2), max_margin_fraction=D('0.5'), max_daily_loss_fraction=D('0.1'),
            require_stop_loss=False))
        self.assertTrue(guard.submit(order('G1')).filled)
        mt5.send_none = True
        result = guard.submit(order('G2'))
        self.assertEqual((result.status, result.reason), ('UNKNOWN', 'BROKER_ERROR_OUTCOME_UNKNOWN'))
        self.assertTrue(guard.halted)
        mt5.send_none = False
        self.assertTrue(guard.submit(order('G3')).reason.startswith('HALTED'))
        self.assertEqual(len(mt5.sent), 2)  # nothing more is sent while halted

    def test_close_position_sends_the_opposite_deal(self):
        broker, mt5 = connected()
        broker.submit(order())
        closed = broker.close_position('1001', 'CLOSE1')
        self.assertEqual((closed.status, closed.position_id), ('FILLED', '1001'))
        sent = mt5.sent[-1]
        self.assertEqual((sent['type'], sent['position'], sent['price'], sent['volume'], sent['comment']),
                         (1, 1001, 1.1, 0.1, 'CLOSE1'))
        self.assertEqual(broker.positions(), ())
        self.assertEqual(broker.close_position('1001', 'CLOSE1'), closed)  # idempotent
        self.assertEqual(broker.close_position('1001', 'CLOSE2').reason, 'UNKNOWN_POSITION')

    def test_positions_not_opened_by_this_system_cannot_be_closed(self):
        broker, mt5 = connected()
        mt5.positions.append(NS(ticket=9, time_msc=1, type=0, volume=1.0, price_open=1.2, sl=0.0, tp=0.0,
                                profit=0.0, symbol='EURUSD.r', comment='manual', magic=0))
        self.assertEqual(broker.close_position('9', 'C9').reason, 'UNKNOWN_POSITION')
        self.assertEqual(mt5.sent, [])

    def test_validation(self):
        for kwargs in ({'magic': 0}, {'magic': 'x'}, {'magic': 5, 'deviation_points': -1},
                       {'magic': 5, 'symbol_map': {'A': 'bad symbol'}}, {'magic': 5, 'expected_server': ''}):
            with self.assertRaises(ValueError):
                MT5DemoBroker(FakeMT5(), **kwargs)
        broker, _ = connected()
        with self.assertRaises(ValueError):
            broker.submit(OrderRequest('X' * 32, 'EURUSD', BUY, '0.1'))  # MT5 comments hold 31 characters
        with self.assertRaises(ValueError):
            broker.submit('not an order')
        with self.assertRaises(MT5Error):
            MT5DemoBroker(FakeMT5(), magic=5).submit(order())  # never connected

    def test_load_mt5_explains_a_missing_package(self):
        with mock.patch.dict(sys.modules, {'MetaTrader5': None}):
            with self.assertRaisesRegex(MT5Error, 'Windows'):
                load_mt5()

    def test_connection_check_cli_is_read_only(self):
        mt5 = FakeMT5()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mt5_check.main(['--login', '123', '--server', 'Demo-Server', '--symbol', 'EURUSD.r'],
                                  mt5_module=mt5, password=PASSWORD)
        report = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual((report['connected'], report['mode'], report['quote']['ask']), (True, 'DEMO', '1.1002'))
        self.assertNotIn(PASSWORD, out.getvalue())
        self.assertEqual(mt5.sent, [])
        self.assertEqual(mt5.shutdowns, 1)

    def test_connection_check_refuses_real_accounts(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = mt5_check.main(['--login', '123', '--server', 'Demo-Server'],
                                  mt5_module=FakeMT5(trade_mode=2), password=PASSWORD)
        report = json.loads(out.getvalue())
        self.assertEqual(code, 1)
        self.assertFalse(report['connected'])
        self.assertNotIn('balance', report)
        self.assertNotIn(PASSWORD, out.getvalue())


if __name__ == '__main__':
    unittest.main()
