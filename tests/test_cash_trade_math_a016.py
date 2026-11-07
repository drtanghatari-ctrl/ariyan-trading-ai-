"""Synthetic cash-trade arithmetic only, not venue filters, fills or market returns."""
import json
import unittest
from dataclasses import replace
from decimal import Decimal as D, localcontext, Inexact, Rounded, ROUND_DOWN
from fractions import Fraction as F

from ariyan_trading.instruments import (
    InstrumentSpec,InstrumentIdentity,AssetClass as A,ProductType as P,
    SettlementType as S,PriceDomain as PD,
)
from ariyan_trading.cash_trade_math import quote_cash_trade,simulate_cash_trade,PRICE_CONVENTION


def spec():
    return InstrumentSpec(InstrumentIdentity('SYNTHETIC','SHARE-1'),'SYNTH',A.EQUITY,P.SHARE,
        'SYNTHETIC COMPANY','USD','USD','SHARE','USD_PER_SHARE','1','0.05','1','1',
        PD.POSITIVE,S.SECURITY_DELIVERY,'SYNTHETIC-CALENDAR','UTC','SYNTHETIC-ACTIONS',
        'NOT_APPLICABLE',0,None,None,None,'SYNTHETIC TERMS ONLY',0)


def config(**changes):
    args={'cash_currency':'USD','cash_step':'0.01','fee_bps':'10','slippage_bps':'10',
          'price_convention':PRICE_CONVENTION}
    args.update(changes)
    return args


def quote(side='BUY',quantity='3',price='10',terms=None,**changes):
    return quote_cash_trade(terms or spec(),side,quantity,price,**config(**changes))


class CashTradeMathA016Tests(unittest.TestCase):
    def test_hand_computed_buy_tick_slippage_fee_and_cash_delta(self):
        q=quote()
        self.assertEqual(q['modeled_fill_price'],'10.05')
        self.assertEqual(q['posted_notional'],'30.15');self.assertEqual(q['fee'],'0.04')
        self.assertEqual(q['cash_delta'],'-30.19');self.assertEqual(q['units_delta'],'3')
        self.assertEqual(q['modeled_slippage_cost'],'0.15')

    def test_hand_computed_sell_tick_slippage_fee_and_cash_delta(self):
        q=quote(side='SELL')
        self.assertEqual(q['modeled_fill_price'],'9.95')
        self.assertEqual(q['posted_notional'],'29.85');self.assertEqual(q['fee'],'0.03')
        self.assertEqual(q['cash_delta'],'29.82');self.assertEqual(q['units_delta'],'-3')

    def test_flat_reference_roundtrip_reconciles_without_double_slippage(self):
        buy=simulate_cash_trade(spec(),'BUY','3','10',opening_cash='100',opening_units='0',**config())
        sell=simulate_cash_trade(spec(),'SELL','3','10',opening_cash=buy['cash_after'],opening_units=buy['units_after'],**config())
        self.assertEqual(buy['cash_after'],'69.81');self.assertEqual(buy['units_after'],'3')
        self.assertEqual(sell['cash_after'],'99.63');self.assertEqual(sell['units_after'],'0')
        self.assertEqual(D(buy['quote']['fee'])+D(sell['quote']['fee']),D('0.07'))
        self.assertEqual(D(buy['quote']['modeled_slippage_cost'])+D(sell['quote']['modeled_slippage_cost']),D('0.30'))

    def test_non_power_of_ten_cash_step_uses_real_grid_not_decimal_places(self):
        terms=replace(spec(),quantity_step='0.1',minimum_quantity='0.1')
        buy=quote(quantity='0.3',price='1.05',terms=terms,cash_step='0.05',fee_bps='0',slippage_bps='0')
        sell=quote(side='SELL',quantity='0.3',price='1.05',terms=terms,cash_step='0.05',fee_bps='0',slippage_bps='0')
        self.assertEqual(buy['exact_modeled_notional'],'0.315')
        self.assertEqual(buy['posted_notional'],'0.35');self.assertEqual(sell['posted_notional'],'0.3')
        self.assertEqual(buy['notional_rounding_adjustment'],'0.035')
        self.assertEqual(sell['notional_rounding_adjustment'],'-0.015')

    def test_zero_costs_preserve_grid_prices_and_have_zero_fee(self):
        q=quote(fee_bps='0',slippage_bps='0')
        self.assertEqual(q['modeled_fill_price'],'10');self.assertEqual(q['fee'],'0')
        self.assertEqual(q['cash_delta'],'-30');self.assertEqual(q['modeled_slippage_cost'],'0')

    def test_fraction_audit_over_exact_non_float_cases(self):
        for side in ('BUY','SELL'):
            for price in ('1','10','123456789012.35'):
                for qty in ('1','3','1234567'):
                    for fee in ('0','0.125','1000'):
                        q=quote(side,qty,price,fee_bps=fee,slippage_bps='0.25',cash_step='0.05')
                        fill=F(q['modeled_fill_price']);posted=F(q['posted_notional']);step=F('0.05')
                        exact=fill*F(qty);cost=F(q['fee']);raw_fee=posted*F(fee)/10000
                        self.assertEqual((fill/F('0.05')).denominator,1)
                        self.assertEqual((posted/step).denominator,1);self.assertEqual((cost/step).denominator,1)
                        self.assertGreaterEqual(cost,raw_fee);self.assertLess(cost-raw_fee,step)
                        if side=='BUY':
                            self.assertGreaterEqual(fill,F(price));self.assertTrue(0<=posted-exact<step)
                            self.assertEqual(F(q['cash_delta']),-posted-cost)
                        else:
                            self.assertLessEqual(fill,F(price));self.assertTrue(0<=exact-posted<step)
                            self.assertEqual(F(q['cash_delta']),posted-cost)

    def test_long_only_balances_no_borrowing_or_overselling(self):
        for side,cash,units in (('BUY','30.18','0'),('SELL','0','2'),('BUY','-1','0'),('BUY','100','-1')):
            with self.assertRaises(ValueError):
                simulate_cash_trade(spec(),side,'3','10',opening_cash=cash,opening_units=units,**config())
        with self.assertRaises(ValueError):
            simulate_cash_trade(spec(),'BUY','1','10',opening_cash='100.005',opening_units='0',**config())

    def test_balance_changes_exactly_match_the_returned_quote(self):
        for side,units in (('BUY','0'),('SELL','3')):
            result=simulate_cash_trade(spec(),side,'3','10',opening_cash='100',opening_units=units,**config())
            self.assertEqual(D(result['cash_after'])-D(result['opening_cash']),D(result['quote']['cash_delta']))
            self.assertEqual(D(result['units_after'])-D(result['opening_units']),D(result['quote']['units_delta']))

    def test_off_grid_existing_holdings_are_not_silently_rounded(self):
        terms=replace(spec(),quantity_step='0.25',minimum_quantity='0.25')
        result=simulate_cash_trade(terms,'SELL','0.25','10',opening_cash='0',opening_units='0.35',**config())
        self.assertEqual(result['units_after'],'0.1')

    def test_spot_and_fund_share_are_explicitly_supported_without_multipliers(self):
        variants=(replace(spec(),asset_class=A.FUND,product=P.FUND_SHARE),
            replace(spec(),asset_class=A.CRYPTO,product=P.SPOT,quantity_unit='TEST_TOKEN',
                    settlement_type=S.ASSET_DELIVERY,corporate_action_reference='NOT_APPLICABLE'),
            replace(spec(),asset_class=A.METAL,product=P.SPOT,quantity_unit='TEST_METAL_UNIT',
                    settlement_type=S.ASSET_DELIVERY,corporate_action_reference='NOT_APPLICABLE'))
        for terms in variants:
            self.assertEqual(quote(terms=terms)['cash_delta'],'-30.19')

    def test_futures_rejected_instead_of_spot_notional_shortcut(self):
        terms=replace(spec(),product=P.FUTURE,quantity_unit='CONTRACT',contract_multiplier='1000',
            settlement_type=S.CASH,roll_reference='SYNTHETIC-ROLL',last_trade_ms=1000,expiry_ms=2000)
        with self.assertRaises(ValueError):quote(terms=terms)

    def test_cash_and_settlement_currency_must_match_no_implicit_fx(self):
        with self.assertRaises(ValueError):quote(cash_currency='EUR')
        with self.assertRaises(ValueError):quote(terms=replace(spec(),settlement_currency='EUR'))

    def test_explicit_price_convention_and_side_required(self):
        for side in ('buy','HOLD',True,None):
            with self.assertRaises(ValueError):quote(side=side)
        for convention in ('OTHER',True,None):
            with self.assertRaises(ValueError):quote(price_convention=convention)

    def test_input_grid_and_minimum_are_checked_without_rounding_quantity(self):
        for qty,price in (('0','10'),('0.5','10'),('1','10.01'),('-1','10')):
            with self.assertRaises(ValueError):quote(quantity=qty,price=price)

    def test_sell_zero_tick_zero_proceeds_and_fee_consumed_dust_rejected(self):
        with self.assertRaises(ValueError):quote(side='SELL',quantity='1',price='0.05',slippage_bps='1000')
        with self.assertRaises(ValueError):quote(side='SELL',quantity='1',price='0.05',slippage_bps='0',cash_step='0.05',fee_bps='1000')
        tiny=replace(spec(),quantity_step='0.00001',minimum_quantity='0.00001')
        with self.assertRaises(ValueError):quote(side='SELL',quantity='0.00001',price='1',terms=tiny,fee_bps='0')

    def test_numeric_types_cost_bounds_and_nonfinite_values_rejected(self):
        for value in (True,0.01,'NaN','Infinity','-1','1000.01','1e24'):
            for name in ('fee_bps','slippage_bps'):
                with self.assertRaises((ValueError,TypeError)):quote(**{name:value})
        for value in (True,0.01,'0','-1','NaN','1e-13'):
            with self.assertRaises((ValueError,TypeError)):quote(cash_step=value)
        for value in (True,1.0,'NaN','1e24'):
            with self.assertRaises((ValueError,TypeError)):quote(quantity=value)

    def test_zero_and_signed_reference_prices_are_not_enabled_by_metadata(self):
        terms=replace(spec(),price_domain=PD.SIGNED)
        for price in ('0','-10'):
            with self.assertRaises(ValueError):quote(price=price,terms=terms)

    def test_unsupported_balance_output_is_rejected_without_silent_rounding(self):
        with self.assertRaises(ValueError):
            simulate_cash_trade(spec(),'BUY','3','10',opening_cash='100',
                opening_units='999999999999999999999999',**config())

    def test_hostile_decimal_context_does_not_change_quotes_or_balances(self):
        expected=quote()
        state=simulate_cash_trade(spec(),'BUY','3','10',opening_cash='100',opening_units='0',**config())
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_DOWN;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
            self.assertEqual(quote(),expected)
            self.assertEqual(simulate_cash_trade(spec(),'BUY','3','10',opening_cash='100',opening_units='0',**config()),state)

    def test_canonical_spellings_json_and_false_claims(self):
        a=quote();b=quote(quantity='3.000',price='10.000',fee_bps='10.000',slippage_bps='10.00',cash_step='0.0100')
        self.assertEqual(a,b);self.assertEqual(json.loads(json.dumps(a)),a)
        for key in ('price_convention_independently_verified','venue_rules_independently_verified',
                    'actual_fill_established','order_admission_established','live_authorized'):
            self.assertIs(a[key],False)
        result=simulate_cash_trade(spec(),'BUY','3','10',opening_cash='100',opening_units='0',**config())
        for key in ('ledger_posted','risk_approval_established','live_authorized'):self.assertIs(result[key],False)
        self.assertNotEqual(a['quote_sha256'],quote(fee_bps='20')['quote_sha256'])

    def test_spec_unchanged_and_legacy_replay_steps_unchanged(self):
        from ariyan_trading.replay import CENT,STEP
        terms=spec();before=terms.to_record();quote(terms=terms)
        self.assertEqual(terms.to_record(),before)
        self.assertEqual(CENT,D('0.01'));self.assertEqual(STEP,D('0.00000001'))


if __name__=='__main__':unittest.main()
