"""Synthetic replay mechanics and causal timing tests; not evidence of strategy edge."""
import json
import unittest
from dataclasses import replace
from decimal import Decimal as D,localcontext,Inexact,Rounded,ROUND_DOWN

from ariyan_trading.instruments import InstrumentSpec,InstrumentIdentity,AssetClass as A,ProductType as P,PriceDomain as PD,SettlementType as S
from ariyan_trading.market_data import Candle
from ariyan_trading.instrument_data import PRICE_BASIS
from ariyan_trading.session_data import SessionCandleSeries
from ariyan_trading.sessions import SessionSchedule,SessionWindow as W,CoverageKind as C
from ariyan_trading.cash_trade_math import PRICE_CONVENTION,quote_cash_trade
from ariyan_trading.session_replay import SessionReplayConfig,run_session_replay,CONTEXT

H=3600000


def series(prices=(10,11,12,13,12,11,10,9,10,11,12,13),windows=None,end=None):
    end=end or len(prices)*H
    windows=windows or (W(0,end,'SYNTHETIC'),)
    schedule=SessionSchedule('SYNTHETIC-V1','UTC',0,end,C.EXHAUSTIVE,windows,'SYNTHETIC ONLY',end)
    spec=InstrumentSpec(InstrumentIdentity('SYNTHETIC','SHARE-1'),'OTHER',A.EQUITY,P.SHARE,
        'SYNTHETIC COMPANY','USD','USD','SHARE','USD_PER_SHARE','1','0.05','1','1',PD.POSITIVE,
        S.SECURITY_DELIVERY,'SYNTHETIC-V1','UTC','SYNTHETIC-ACTIONS','NOT_APPLICABLE',0,end,
        None,None,'SYNTHETIC TERMS ONLY',end)
    timestamps=[t for w in windows for t in range(w.open_ms,w.close_ms,H)]
    if len(timestamps)!=len(prices):raise AssertionError('Fixture mismatch')
    candles=tuple(Candle(t,D(p),D(p),D(p),D(p),D(10)) for t,p in zip(timestamps,prices))
    return SessionCandleSeries(candles,'SYNTH','SYNTHETIC ONLY','0'*64,spec,schedule,H,0,0,end,end,
        PRICE_BASIS,'SHARE','SYNTHETIC CALLER MAPPING')


def config(**changes):
    values={'opening_cash':'1000','cash_currency':'USD','cash_step':'0.01','fee_bps':'10',
        'slippage_bps':'10','price_convention':PRICE_CONVENTION,'short_window':1,'long_window':2,
        'max_close_drawdown_pct':'100'}
    values.update(changes)
    return SessionReplayConfig(**values)


class SessionReplayA017Tests(unittest.TestCase):
    def test_same_window_next_open_signal_timing_and_warmup(self):
        r=run_session_replay(series(),config())
        self.assertTrue(r['trades'])
        self.assertEqual(r['trades'][0]['fill_timestamp_ms'],2*H)
        self.assertEqual(r['trades'][0]['signal_available_at_ms'],2*H)
        for t in r['trades']:
            self.assertLessEqual(t['signal_available_at_ms'],t['fill_timestamp_ms'])
        self.assertEqual(r['summary']['session_warmup_resets'],1)

    def test_independent_postings_fees_final_mark_and_quotes_reconcile(self):
        s=series();c=config();r=run_session_replay(s,c)
        cash=D(c.opening_cash);units=D(0);fees=D(0)
        by_time={b.timestamp_ms:b for b in s.candles}
        with localcontext(CONTEXT):
            for trade in r['trades']:
                q=trade['quote'];quantity=D(q['quantity']);notional=D(q['posted_notional']);fee=D(q['fee'])
                if trade['side']=='BUY':cash-=notional+fee;units+=quantity
                else:cash+=notional-fee;units-=quantity
                fees+=fee
                self.assertEqual(cash,D(trade['cash_after']));self.assertEqual(units,D(trade['units_after']))
                self.assertGreaterEqual(cash,0);self.assertGreaterEqual(units,0)
                fresh=quote_cash_trade(s.spec,trade['side'],q['quantity'],by_time[trade['fill_timestamp_ms']].open,
                    cash_currency=c.cash_currency,cash_step=c.cash_step,fee_bps=c.fee_bps,
                    slippage_bps=c.slippage_bps,price_convention=c.price_convention)
                self.assertEqual(q['quote_sha256'],fresh['quote_sha256'])
            self.assertEqual(fees,D(r['summary']['total_fees']))
            self.assertEqual(cash+units*s.candles[-1].close,D(r['summary']['final_marked_equity']))

    def test_every_buy_respects_fee_inclusive_budget_and_post_cost_exposure(self):
        s=series();c=config();r=run_session_replay(s,c)
        cash=D(c.opening_cash);units=D(0)
        with localcontext(CONTEXT):
            for trade in r['trades']:
                q=trade['quote'];reference=D(q['reference_price']);qty=D(q['quantity'])
                if trade['side']=='BUY':
                    outlay=D(q['posted_notional'])+D(q['fee']);equity=cash+units*reference
                    self.assertLessEqual(outlay,min(cash,equity*D(c.max_buy_fraction)))
                    after=D(trade['cash_after']);exposure=(units+qty)*reference
                    self.assertLessEqual(exposure,D(c.max_position_fraction)*(after+exposure))
                    # One more lot must violate cash/budget/exposure: check a full A016 quote independently.
                    extra=quote_cash_trade(s.spec,'BUY',qty+s.spec.quantity_step,reference,cash_currency='USD',
                        cash_step=c.cash_step,fee_bps=c.fee_bps,slippage_bps=c.slippage_bps,price_convention=PRICE_CONVENTION)
                    bigger=D(extra['posted_notional'])+D(extra['fee']);big_exposure=(units+qty+s.spec.quantity_step)*reference
                    self.assertTrue(bigger>min(cash,equity*D(c.max_buy_fraction)) or
                        big_exposure>D(c.max_position_fraction)*(cash-bigger+big_exposure))
                cash=D(trade['cash_after']);units=D(trade['units_after'])

    def test_session_resets_signals_and_warmup_but_carries_holdings(self):
        s=series((10,11,12,13,20,21,22,23),windows=(W(0,4*H,'A'),W(24*H,28*H,'B')),end=28*H)
        r=run_session_replay(s,config())
        self.assertEqual(r['summary']['session_warmup_resets'],2)
        first=r['decisions'][4]
        self.assertEqual(first['execution_outcome'],'SESSION_START_NO_FILL')
        self.assertEqual(first['execution_signal'],'WARMUP')
        self.assertGreater(D(r['equity_curve'][4]['units']),0)
        self.assertFalse(any(t['fill_timestamp_ms'] in (24*H,25*H) for t in r['trades']))

    def test_adjacent_declared_windows_reset_even_without_elapsed_gap(self):
        s=series((10,11,12,13,14,15),windows=(W(0,3*H,'A'),W(3*H,6*H,'B')))
        r=run_session_replay(s,config())
        self.assertEqual(r['decisions'][3]['execution_outcome'],'SESSION_START_NO_FILL')
        self.assertFalse(any(t['fill_timestamp_ms'] in (3*H,4*H) for t in r['trades']))

    def test_future_price_changes_do_not_change_earlier_trades_curve_or_decisions(self):
        s=series();a=run_session_replay(s,config())
        bars=tuple(replace(b,open=D(100),high=D(100),low=D(100),close=D(100)) if i>=7 else b for i,b in enumerate(s.candles))
        b=run_session_replay(replace(s,candles=bars),config())
        self.assertEqual(a['equity_curve'][:7],b['equity_curve'][:7]);self.assertEqual(a['decisions'][:7],b['decisions'][:7])
        self.assertEqual([t for t in a['trades'] if t['fill_timestamp_ms']<7*H],
                         [t for t in b['trades'] if t['fill_timestamp_ms']<7*H])

    def test_current_bar_close_volume_and_high_do_not_change_its_open_fill(self):
        s=series();a=run_session_replay(s,config());bars=list(s.candles)
        bars[2]=replace(bars[2],close=D(100),high=D(100),volume=D(0))
        b=run_session_replay(replace(s,candles=tuple(bars)),config())
        self.assertEqual(a['trades'][0],b['trades'][0])

    def test_previous_zero_volume_blocks_fill_without_using_current_volume(self):
        s=series();bars=list(s.candles);bars[1]=replace(bars[1],volume=D(0))
        r=run_session_replay(replace(s,candles=tuple(bars)),config())
        self.assertEqual(r['decisions'][2]['execution_outcome'],'SKIP_PREVIOUS_ZERO_VOLUME')
        self.assertFalse(any(t['fill_timestamp_ms']==2*H for t in r['trades']))

    def test_missing_unknown_boundary_and_off_session_data_rejected(self):
        s=series();missing=replace(s,candles=s.candles[:3]+s.candles[4:])
        partial=replace(s,schedule=replace(s.schedule,coverage_kind=C.PARTIAL))
        outside=replace(s,schedule=replace(s.schedule,coverage_start_ms=H,windows=(W(H,12*H,'A'),)))
        boundary=replace(s,schedule=replace(s.schedule,windows=(W(H//2,12*H,'A'),)))
        closed=replace(s,schedule=replace(s.schedule,windows=(W(H,12*H,'A'),)))
        for value in (missing,partial,outside,boundary,closed):
            with self.assertRaises(ValueError):run_session_replay(value,config())

    def test_drawdown_halt_latches_exits_then_never_restarts_buys(self):
        s=series((10,11,12,13,1,1,20,21,22,23))
        r=run_session_replay(s,config(max_buy_fraction='0.5',max_position_fraction='0.8',max_close_drawdown_pct='5'))
        self.assertTrue(r['summary']['drawdown_halted'])
        halt=r['summary']['halt_available_at_ms']
        self.assertTrue(any(t['side']=='SELL' and t['fill_timestamp_ms']>=halt for t in r['trades']))
        self.assertFalse(any(t['side']=='BUY' and t['fill_timestamp_ms']>=halt for t in r['trades']))
        self.assertEqual(r['summary']['final_units'],'0')

    def test_drawdown_exit_waits_after_closure_for_same_window_volume_evidence(self):
        s=series((10,11,12,1,1,2,3,4),windows=(W(0,4*H,'A'),W(24*H,28*H,'B')),end=28*H)
        r=run_session_replay(s,config(max_buy_fraction='0.5',max_position_fraction='0.8',max_close_drawdown_pct='5'))
        self.assertTrue(r['summary']['drawdown_halted'])
        self.assertFalse(any(t['fill_timestamp_ms']==24*H for t in r['trades']))
        self.assertTrue(any(t['fill_timestamp_ms']==25*H and t['side']=='SELL' for t in r['trades']))

    def test_drawdown_exit_is_not_guaranteed_when_prior_volume_zero(self):
        s=series((10,11,12,1,1,1,1))
        bars=tuple(replace(b,volume=D(0)) if i>=3 else b for i,b in enumerate(s.candles))
        r=run_session_replay(replace(s,candles=bars),config(max_buy_fraction='0.5',max_position_fraction='0.8',max_close_drawdown_pct='5'))
        self.assertTrue(r['summary']['drawdown_halted']);self.assertGreater(D(r['summary']['final_units']),0)
        self.assertTrue(any(d['execution_outcome']=='SKIP_PREVIOUS_ZERO_VOLUME' for d in r['decisions'][4:]))

    def test_gap_exposure_can_exceed_cap_and_new_buys_are_blocked(self):
        s=series((10,11,12,13,1000,1001,1002,1003),windows=(W(0,4*H,'A'),W(24*H,28*H,'B')),end=28*H)
        r=run_session_replay(s,config())
        self.assertTrue(r['decisions'][4]['position_cap_exceeded_at_open'])
        self.assertFalse(any(t['side']=='BUY' and t['fill_timestamp_ms']>=24*H for t in r['trades']))

    def test_minimum_size_can_prevent_buys_without_making_invalid_fills(self):
        s=series();s=replace(s,spec=replace(s.spec,minimum_quantity='100'))
        r=run_session_replay(s,config())
        self.assertEqual(r['trades'],[]);self.assertEqual(r['summary']['final_marked_equity'],'1000')

    def test_fractional_quantity_and_non_power_of_ten_cash_grids_are_preserved(self):
        s=series();s=replace(s,spec=replace(s.spec,quantity_step='0.25',minimum_quantity='0.25'))
        r=run_session_replay(s,config(cash_step='0.05'))
        self.assertTrue(r['trades'])
        for trade in r['trades']:
            self.assertEqual(D(trade['quote']['quantity']) % D('0.25'),0)
            self.assertEqual(D(trade['cash_after']) % D('0.05'),0)

    def test_crypto_and_fund_share_profiles_use_the_same_explicit_cash_model(self):
        s=series()
        crypto=replace(s.spec,asset_class=A.CRYPTO,product=P.SPOT,quantity_unit='TEST_TOKEN',
                       settlement_type=S.ASSET_DELIVERY,corporate_action_reference='NOT_APPLICABLE')
        fund=replace(s.spec,asset_class=A.FUND,product=P.FUND_SHARE)
        for terms in (crypto,fund):
            r=run_session_replay(replace(s,spec=terms,volume_unit=terms.quantity_unit),config())
            self.assertTrue(r['trades'])
            self.assertEqual(r['intake']['instrument_spec_sha256'],terms.fingerprint())

    def test_terminal_holdings_not_liquidated_and_mark_staleness_is_explicit(self):
        s=series((10,11,12,13),windows=(W(0,4*H,'A'),),end=24*H)
        r=run_session_replay(s,config())
        self.assertGreater(D(r['summary']['final_units']),0)
        self.assertTrue(r['summary']['last_mark_precedes_requested_end'])
        self.assertEqual(r['summary']['last_mark_available_at_ms'],4*H)

    def test_empty_warmup_and_resource_limits(self):
        s=series()
        with self.assertRaises(ValueError):run_session_replay(replace(s,candles=(),schedule=replace(s.schedule,windows=())),config())
        with self.assertRaises(ValueError):run_session_replay(s,config(max_trades=1))
        short=run_session_replay(series((10,11)),config(long_window=5))
        self.assertEqual(short['trades'],[])
        # Limit all grid slots, including closures, before replay.
        long_scope=replace(s,end_exclusive_ms=10001*H,as_of_ms=10001*H,
            spec=replace(s.spec,effective_until_ms=10001*H),schedule=replace(s.schedule,coverage_end_ms=10001*H))
        with self.assertRaises(ValueError):run_session_replay(long_scope,config())

    def test_futures_fx_and_invalid_configuration_rejected_before_noop_run(self):
        s=series((10,11))
        fut=replace(s.spec,product=P.FUTURE,quantity_unit='CONTRACT',contract_multiplier='1000',
                    settlement_type=S.CASH,roll_reference='SYNTH-ROLL',last_trade_ms=2*H,expiry_ms=3*H)
        with self.assertRaises(ValueError):run_session_replay(replace(s,spec=fut,volume_unit='CONTRACT'),config())
        with self.assertRaises(ValueError):run_session_replay(s,config(cash_currency='EUR'))
        for changes in ({'opening_cash':'0'},{'cash_step':'0'},{'opening_cash':'1000.005'},
            {'max_buy_fraction':'0'},{'max_position_fraction':'1.01'},{'max_close_drawdown_pct':'0'},
            {'fee_bps':True},{'long_window':True},{'max_trades':1001},{'price_convention':'OTHER'}):
            with self.assertRaises((ValueError,TypeError)):config(**changes)

    def test_unexecutable_sell_does_not_fabricate_liquidation(self):
        s=series((10,11,12,'0.05','0.05','0.05'))
        c=config(max_buy_fraction='0.01',max_position_fraction='1',cash_step='0.05',fee_bps='1000',slippage_bps='1000',max_close_drawdown_pct='0.01')
        # Use larger cash so at least one whole-share buy can be admitted.
        c=replace(c,opening_cash='10000')
        r=run_session_replay(s,c)
        self.assertTrue(r['summary']['drawdown_halted'])
        self.assertGreater(r['summary']['unexecutable_cash_model_attempts'],0)
        self.assertGreater(D(r['summary']['final_units']),0)

    def test_context_isolation_json_and_no_authority(self):
        s=series();expected=run_session_replay(s,config())
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
            self.assertEqual(run_session_replay(s,config()),expected)
        self.assertEqual(json.loads(json.dumps(expected)),expected)
        for key in ('ledger_posted','strategy_promoted','production_risk_approval_established','live_authorized'):
            self.assertIs(expected[key],False)
        self.assertEqual(s.to_report(),expected['intake'])


if __name__=='__main__':unittest.main()
