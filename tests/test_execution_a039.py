"""Synthetic quotes and instruments only; hand-computed expectations."""
import unittest
from decimal import Decimal as D

from ariyan_trading.execution import (
    AccountState, Broker, BrokerMode, GuardedBroker, OrderRequest, OrderResult, OrderSide,
    PaperBroker, Position, Quote, RiskLimits, SignalExecutor,
)
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.market_data import Candle
from ariyan_trading.strategies import Signal, Strategy

SYM = 'EURUSD'
BUY, SELL = OrderSide.BUY, OrderSide.SELL


def spec(quote='USD'):
    return MarginInstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'EX-001'), display_symbol=SYM,
        asset_class=A.FOREX, product=P.FX_MARGIN, base_label='EUR', quote_currency=quote,
        contract_size='100000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
        price_step='0.00001', pip_size='0.0001', initial_margin_rate='0.01',
        maintenance_margin_rate='0.005', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-FX-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=0, effective_until_ms=None, source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)


def broker(cash='10000', **kwargs):
    b = PaperBroker({SYM: spec()}, cash, 'USD', **kwargs)
    b.set_quote(SYM, '1.10000', '1.10020', 1000)
    return b


def order(cid='O1', side=BUY, lots='1', **kwargs):
    return OrderRequest(cid, SYM, side, lots, **kwargs)


def limits(**changes):
    terms = dict(allowed_symbols=frozenset({SYM}), max_lots_per_order=D(5), max_open_positions=3,
                 max_total_lots=D(8), max_margin_fraction=D('0.5'), max_daily_loss_fraction=D('0.1'),
                 require_stop_loss=False)
    terms.update(changes)
    return RiskLimits(**terms)


class PaperBrokerA039Tests(unittest.TestCase):
    def test_buy_fills_at_ask_and_accounts_for_spread_and_margin(self):
        b = broker()
        result = b.submit(order())
        self.assertEqual((result.status, result.price, result.lots, result.position_id),
                         ('FILLED', D('1.10020'), D(1), 'P000001'))
        account = b.account()
        self.assertEqual(account.margin_used, D('1100.2000000'))  # 1 x 100000 x 1.1002 x 0.01
        self.assertEqual(account.equity, D(9980))                  # the 2-pip spread is already lost
        self.assertEqual(account.free_margin, D('8879.80'))
        self.assertIs(account.mode, BrokerMode.PAPER)

    def test_profit_on_close_and_commission(self):
        b = broker(commission_per_lot_per_side='3.5')
        b.submit(order())
        b.set_quote(SYM, '1.10500', '1.10520', 2000)
        self.assertEqual(b.positions()[0].unrealized_pnl, D(480))
        closed = b.close_position('P000001', 'C1')
        self.assertEqual((closed.price, closed.reason), (D('1.10500'), 'CLOSE_REQUEST'))
        self.assertEqual(b.account().balance, D('10473.0'))  # 10000 + 480 - 3.5 - 3.5
        self.assertEqual(b.positions(), ())

    def test_sell_fills_at_bid_and_profits_when_price_falls(self):
        b = broker()
        b.submit(order(side=SELL))
        b.set_quote(SYM, '1.09000', '1.09020', 2000)
        b.close_position('P000001', 'C1')
        self.assertEqual(b.account().balance, D(10000) + D('1.10000') * 100000 - D('1.09020') * 100000)

    def test_stop_loss_gap_fills_at_the_worse_quote(self):
        b = broker()
        b.submit(order(stop_loss='1.09800'))
        b.set_quote(SYM, '1.09900', '1.09920', 2000)
        self.assertEqual(len(b.positions()), 1)
        b.set_quote(SYM, '1.09500', '1.09520', 3000)  # gaps through the stop
        self.assertEqual(b.positions(), ())
        self.assertEqual(b.account().balance, D(10000) + (D('1.09500') - D('1.10020')) * 100000)
        self.assertEqual(b.journal()[-1]['reason'], 'STOP_LOSS')

    def test_take_profit_triggers(self):
        b = broker()
        b.submit(order(take_profit='1.10800'))
        b.set_quote(SYM, '1.10800', '1.10820', 2000)
        self.assertEqual(b.positions(), ())
        self.assertEqual(b.account().balance, D(10000) + D(780))
        self.assertEqual(b.journal()[-1]['reason'], 'TAKE_PROFIT')

    def test_short_stop_loss_uses_the_ask(self):
        b = broker()
        b.submit(order(side=SELL, stop_loss='1.10500'))
        b.set_quote(SYM, '1.10480', '1.10500', 2000)
        self.assertEqual(b.positions(), ())
        self.assertEqual(b.account().balance, D(10000) + (D('1.10000') - D('1.10500')) * 100000)

    def test_stop_out_closes_positions_below_maintenance(self):
        b = broker('2000')
        self.assertTrue(b.submit(order(lots='1.5')).filled)  # margin 1650.30 fits free margin 1970
        b.set_quote(SYM, '1.09300', '1.09320', 2000)          # equity 920 > maintenance 819.75
        self.assertEqual(len(b.positions()), 1)
        b.set_quote(SYM, '1.09200', '1.09220', 3000)          # equity 770 <= maintenance 819
        self.assertEqual(b.positions(), ())
        self.assertEqual(b.account().balance, D(2000) + (D('1.09200') - D('1.10020')) * 150000)
        self.assertEqual(b.journal()[-1]['reason'], 'STOP_OUT')

    def test_rejections(self):
        b = broker('2000')
        cases = {
            'LOTS_OUTSIDE_INSTRUMENT_TERMS': order('A', lots='0.001'),
            'LOTS_OUTSIDE_INSTRUMENT_TERMS ': order('A2', lots='100.01'),
            'INSUFFICIENT_MARGIN': order('B', lots='5'),
            'STOP_LOSS_ON_WRONG_SIDE': order('C', stop_loss='1.20000'),
            'TAKE_PROFIT_ON_WRONG_SIDE': order('D', take_profit='1.00000'),
            'STOP_LOSS_OFF_GRID': order('E', stop_loss='1.0980001'),
        }
        for reason, request in cases.items():
            result = b.submit(request)
            self.assertEqual((result.status, result.reason), ('REJECTED', reason.strip()), reason)
        unknown = b.submit(OrderRequest('F', 'GBPUSD', BUY, '1'))
        self.assertEqual(unknown.reason, 'UNKNOWN_SYMBOL')
        self.assertEqual(b.account().balance, D(2000))

    def test_orders_are_idempotent_and_conflicts_are_rejected(self):
        b = broker()
        first = b.submit(order('SAME'))
        again = b.submit(order('SAME'))
        self.assertEqual(first, again)
        self.assertEqual(len(b.positions()), 1)
        conflict = b.submit(order('SAME', lots='2'))
        self.assertEqual(conflict.reason, 'DUPLICATE_ID_CONFLICT')
        self.assertEqual(b.close_position('P000001', 'CL'), b.close_position('P000001', 'CL'))
        self.assertEqual(b.close_position('P999999', 'CL2').reason, 'UNKNOWN_POSITION')

    def test_conversion_rate_scales_margin_and_pnl(self):
        b = PaperBroker({SYM: spec()}, '10000', 'EUR', rates={'USD': '0.8'})
        b.set_quote(SYM, '1.10000', '1.10020', 1000)
        b.submit(order())
        self.assertEqual(b.account().margin_used, D('880.16000000'))  # 1100.20 USD x 0.8
        b.set_quote(SYM, '1.10500', '1.10520', 2000)
        self.assertEqual(b.positions()[0].unrealized_pnl, D(384))      # 480 USD x 0.8
        with self.assertRaises(ValueError):
            PaperBroker({SYM: spec()}, '10000', 'EUR')

    def test_quote_validation_and_construction(self):
        b = broker()
        for args in ((SYM, '1.1002', '1.1000', 2000), (SYM, '1.100001', '1.10002', 2000),
                     (SYM, '1.1', '1.1002', 500), (SYM, '0', '1', 2000), ('XXX', '1', '1', 2000)):
            with self.assertRaises((ValueError, TypeError)):
                b.set_quote(*args)
        with self.assertRaises(ValueError):
            b.quote('GBPUSD')
        for args in (({}, '1', 'USD'), ({SYM: object()}, '1', 'USD'), ({SYM: spec()}, '0', 'USD'),
                     ({SYM: spec()}, '1', '')):
            with self.assertRaises(ValueError):
                PaperBroker(*args)
        with self.assertRaises(ValueError):
            OrderRequest('bad id', SYM, BUY, '1')
        with self.assertRaises(ValueError):
            OrderRequest('X', SYM, 'BUY', '1')
        with self.assertRaises((ValueError, TypeError)):
            OrderRequest('X', SYM, BUY, 1.5)


class FakeLive(Broker):
    mode = BrokerMode.LIVE

    def account(self): raise AssertionError('must not be used')
    def positions(self): raise AssertionError('must not be used')
    def quote(self, symbol): raise AssertionError('must not be used')
    def submit(self, request): raise AssertionError('must not be used')
    def close_position(self, position_id, client_order_id): raise AssertionError('must not be used')


class Flaky(PaperBroker):
    def __init__(self, *args, fail='submit', **kwargs):
        super().__init__(*args, **kwargs)
        self.fail = fail

    def submit(self, request):
        if self.fail == 'submit':
            raise RuntimeError('network down')
        return super().submit(request)

    def positions(self):
        if self.fail == 'state':
            raise RuntimeError('state unavailable')
        return super().positions()


class GuardedBrokerA039Tests(unittest.TestCase):
    def guarded(self, cash='10000', **changes):
        return GuardedBroker(broker(cash), limits(**changes))

    def test_live_broker_is_refused(self):
        with self.assertRaises(ValueError):
            GuardedBroker(FakeLive(), limits())

    def test_mode_flip_to_live_halts(self):
        inner = broker()
        g = GuardedBroker(inner, limits())
        inner.__class__ = type('Flipped', (PaperBroker,), {'mode': BrokerMode.LIVE})
        result = g.submit(order())
        self.assertEqual(result.status, 'REJECTED')
        self.assertTrue(g.halted)
        self.assertEqual(g.halt_reason, 'LIVE_MODE_DETECTED')

    def test_limit_rejections(self):
        g = self.guarded(require_stop_loss=True)
        cases = (('STOP_LOSS_REQUIRED', order('A')),
                 ('SYMBOL_NOT_ALLOWED', OrderRequest('B', 'GBPUSD', BUY, '1', stop_loss='1')),
                 ('LOTS_ABOVE_ORDER_LIMIT', order('C', lots='6', stop_loss='1.09')))
        for reason, request in cases:
            self.assertEqual(g.submit(request).reason, reason)
        self.assertEqual(g.positions(), ())

    def test_position_and_total_lot_limits(self):
        g = self.guarded(max_open_positions=2, max_total_lots=D(3))
        self.assertTrue(g.submit(order('A', lots='2')).filled)
        self.assertEqual(g.submit(order('B', lots='1.5')).reason, 'TOTAL_LOTS_ABOVE_LIMIT')
        self.assertTrue(g.submit(order('C', lots='1')).filled)
        self.assertEqual(g.submit(order('D', lots='0.01')).reason, 'TOO_MANY_POSITIONS')

    def test_margin_fraction_limit_undoes_the_fill(self):
        g = self.guarded('2000', max_margin_fraction=D('0.5'))
        result = g.submit(order('BIG', lots='1.5'))  # margin 1650 of ~1970 equity is above 50%
        self.assertEqual((result.status, result.reason), ('REJECTED', 'MARGIN_FRACTION_ABOVE_LIMIT_UNDONE'))
        self.assertEqual(g.positions(), ())
        self.assertTrue(g.submit(order('SMALL', lots='0.5')).filled)

    def test_daily_loss_halts_and_blocks_new_orders_but_not_closing(self):
        inner = broker()
        g = GuardedBroker(inner, limits(max_daily_loss_fraction=D('0.05')))
        self.assertTrue(g.submit(order('A', lots='1')).filled)
        inner.set_quote(SYM, '1.04000', '1.04020', 2000)   # equity falls about 6%
        result = g.submit(order('B', lots='0.5'))
        self.assertEqual(result.reason, 'HALTED:DAILY_LOSS_LIMIT')
        self.assertTrue(g.halted)
        self.assertEqual(g.submit(order('C')).reason, 'HALTED:DAILY_LOSS_LIMIT')
        closed = g.flatten()
        self.assertTrue(all(r.filled for r in closed))
        self.assertEqual(g.positions(), ())
        g.resume()
        self.assertFalse(g.halted)
        self.assertTrue(g.submit(order('D', lots='0.5')).filled)

    def test_manual_kill_switch(self):
        g = self.guarded()
        g.halt()
        self.assertEqual(g.submit(order()).reason, 'HALTED:MANUAL_KILL_SWITCH')

    def test_unknown_outcome_halts_trading(self):
        g = GuardedBroker(Flaky({SYM: spec()}, '10000', 'USD', fail='submit'), limits())
        g._broker.set_quote(SYM, '1.10000', '1.10020', 1000)
        result = g.submit(order('A'))
        self.assertEqual((result.status, result.reason), ('UNKNOWN', 'BROKER_ERROR_OUTCOME_UNKNOWN'))
        self.assertTrue(g.halted)
        self.assertEqual(g.submit(order('B')).reason, 'HALTED:UNKNOWN_ORDER_OUTCOME')
        self.assertEqual(g.submit(order('A')).status, 'UNKNOWN')  # the same ID is never resubmitted

    def test_unavailable_state_fails_closed(self):
        g = GuardedBroker(Flaky({SYM: spec()}, '10000', 'USD', fail='none'), limits())
        g._broker.set_quote(SYM, '1.10000', '1.10020', 1000)
        g._broker.fail = 'state'
        self.assertEqual(g.submit(order()).reason, 'HALTED:BROKER_STATE_UNAVAILABLE')
        self.assertTrue(g.halted)

    def test_idempotency_through_the_guard(self):
        g = self.guarded()
        a = g.submit(order('X'))
        self.assertEqual(a, g.submit(order('X')))
        self.assertEqual(g.submit(order('X', lots='2')).reason, 'DUPLICATE_ID_CONFLICT')
        self.assertEqual(len(g.positions()), 1)

    def test_limit_validation(self):
        for changes in ({'allowed_symbols': frozenset()}, {'allowed_symbols': {SYM}},
                        {'max_margin_fraction': D(2)}, {'max_daily_loss_fraction': D(0)},
                        {'max_open_positions': 0}, {'require_stop_loss': 1}, {'max_lots_per_order': D(0)}):
            with self.assertRaises((ValueError, TypeError)):
                limits(**changes)
        with self.assertRaises(ValueError):
            GuardedBroker(object(), limits())


class Follow(Strategy):
    name = 'follow'
    lookback = 2

    def target(self, history):
        if history[-1].close > history[-2].close:
            return Signal.LONG
        if history[-1].close < history[-2].close:
            return Signal.SHORT
        return Signal.FLAT


def candle(i, price):
    p = D(price)
    return Candle(i * 60000, p, p, p, p, D(1))


class SignalExecutorA039Tests(unittest.TestCase):
    def run_prices(self, prices, **kwargs):
        inner = PaperBroker({SYM: spec()}, '100000', 'USD')
        g = GuardedBroker(inner, limits(require_stop_loss=kwargs.get('stop') is not None, max_margin_fraction=D(1)))
        executor = SignalExecutor(g, Follow(), SYM, '1', 'RUN1', stop_distance=kwargs.get('stop'))
        for i, price in enumerate(prices):
            inner.set_quote(SYM, price, str(D(price) + D('0.00020')), (i + 1) * 60000)
            executor.on_candle(candle(i, price))
        return inner, executor

    def test_follows_signals_and_reverses(self):
        inner, executor = self.run_prices(['1.10000', '1.10100', '1.10200', '1.10100', '1.10000'])
        sides = [p.side for p in inner.positions()]
        self.assertEqual(sides, [SELL])
        ids = [r.client_order_id for r in executor.log]
        self.assertEqual(len(set(ids)), len(ids))  # unique
        self.assertEqual(ids[0], 'RUN1-O000001')
        reasons = [e['reason'] for e in inner.journal()]
        self.assertEqual(reasons.count('CLOSE_REQUEST'), 1)

    def test_flat_signal_closes_and_equal_prices_hold_nothing(self):
        inner, _ = self.run_prices(['1.10000', '1.10100', '1.10100'])
        self.assertEqual(inner.positions(), ())

    def test_stop_distance_is_applied_and_checked(self):
        inner, _ = self.run_prices(['1.10000', '1.10100'], stop='0.00500')
        position, = inner.positions()
        self.assertEqual(position.stop_loss, D('1.10120') - D('0.00500'))

    def test_a_restarted_executor_replaying_candles_cannot_double_submit(self):
        inner = PaperBroker({SYM: spec()}, '100000', 'USD')
        first = SignalExecutor(inner, Follow(), SYM, '1', 'RUN2')
        inner.set_quote(SYM, '1.10000', '1.10020', 60000)
        first.on_candle(candle(0, '1.10000'))
        inner.set_quote(SYM, '1.10100', '1.10120', 120000)
        first.on_candle(candle(1, '1.10100'))
        self.assertEqual(len(inner.positions()), 1)
        # Process restarts: a new executor with the same run ID replays the same candles.
        second = SignalExecutor(inner, Follow(), SYM, '1', 'RUN2')
        second.on_candle(candle(0, '1.10000'))
        second.on_candle(candle(1, '1.10100'))
        self.assertEqual(len(inner.positions()), 1)
        # Even a forced resubmission with the same deterministic ID returns the original fill.
        again = inner.submit(OrderRequest('RUN2-O000001', SYM, BUY, '1'))
        self.assertEqual((again.status, again.position_id), ('FILLED', 'P000001'))
        self.assertEqual(len(inner.positions()), 1)

    def test_executor_validation(self):
        inner = PaperBroker({SYM: spec()}, '1000', 'USD')
        for args in ((object(), Follow(), SYM, '1', 'R'), (inner, object(), SYM, '1', 'R'),
                     (inner, Follow(), SYM, '0', 'R'), (inner, Follow(), SYM, '1', 'bad id!')):
            with self.assertRaises((ValueError, TypeError)):
                SignalExecutor(*args)


if __name__ == '__main__':
    unittest.main()
