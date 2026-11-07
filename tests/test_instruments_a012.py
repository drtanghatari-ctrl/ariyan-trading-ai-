"""Synthetic instrument terms only; no real venue specifications or prices."""
import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, localcontext, ROUND_UP, Inexact, Rounded

from ariyan_trading.instruments import (
    AssetClass as A, ProductType as P, PriceDomain as PD, SettlementType as S,
    InstrumentIdentity, InstrumentSpec, spec_from_record,
)


def crypto():
    return InstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-VENUE', 'CRYPTO-PAIR-001'),
        display_symbol='BTC/USD', asset_class=A.CRYPTO, product=P.SPOT,
        underlying_label='SYNTHETIC BTC test asset', quote_currency='USD', settlement_currency='USD',
        quantity_unit='BTC', price_unit='USD_PER_BTC', contract_multiplier='1',
        price_step='0.05', quantity_step='0.00001', minimum_quantity='0.00002',
        price_domain=PD.POSITIVE, settlement_type=S.ASSET_DELIVERY,
        calendar_reference='SYNTHETIC-24X7-V1', timezone_label='UTC',
        corporate_action_reference='NOT_APPLICABLE', roll_reference='NOT_APPLICABLE',
        effective_from_ms=1000, effective_until_ms=None, last_trade_ms=None, expiry_ms=None,
        source_label='SYNTHETIC TEST ONLY; not real venue terms', observed_at_ms=2000)


def future(asset=A.ENERGY):
    return replace(crypto(), identity=InstrumentIdentity('SYNTHETIC-FUTURES', 'CONCRETE-2024-09'),
        display_symbol='SYNTHETIC-OIL-2024-09', asset_class=asset, product=P.FUTURE,
        underlying_label='SYNTHETIC commodity', quantity_unit='CONTRACT', price_unit='USD_PER_BARREL',
        contract_multiplier='1000', quantity_step='1', minimum_quantity='1',
        price_step='0.01', price_domain=PD.SIGNED, settlement_type=S.CASH,
        calendar_reference='SYNTHETIC-SESSIONS-V1', timezone_label='America/New_York',
        roll_reference='SYNTHETIC-NO-AUTOMATIC-ROLL-V1', last_trade_ms=3000, expiry_ms=4000)


class InstrumentsA012Tests(unittest.TestCase):
    def test_identity_uses_venue_and_instrument_id_not_display_symbol(self):
        base=crypto()
        renamed=replace(base,display_symbol='ANOTHER DISPLAY NAME')
        other=replace(base,identity=InstrumentIdentity('ANOTHER-VENUE','CRYPTO-PAIR-001'))
        self.assertEqual(base.identity,renamed.identity)
        self.assertEqual(base.identity.fingerprint(),renamed.identity.fingerprint())
        self.assertNotEqual(base.identity.fingerprint(),other.identity.fingerprint())
        self.assertNotEqual(base.fingerprint(),renamed.fingerprint())

    def test_stocks_funds_metals_and_energy_are_distinct_metadata(self):
        for asset,product in ((A.EQUITY,P.SHARE),(A.FUND,P.FUND_SHARE)):
            spec=replace(crypto(),asset_class=asset,product=product,quantity_unit='SHARE',
                price_unit='USD_PER_SHARE',settlement_type=S.SECURITY_DELIVERY,
                calendar_reference='SYNTHETIC-EQUITY-SESSIONS-V1',timezone_label='America/New_York',
                corporate_action_reference='SYNTHETIC-ACTIONS-V1')
            self.assertEqual(spec_from_record(spec.to_record()),spec)
            with self.assertRaises(ValueError):replace(spec,quantity_unit='CONTRACT')
        for asset,label in ((A.METAL,'SYNTHETIC GOLD'),(A.METAL,'SYNTHETIC SILVER'),(A.ENERGY,'SYNTHETIC OIL')):
            spec=replace(crypto(),asset_class=asset,underlying_label=label,quantity_unit='DECLARED_UNIT')
            self.assertEqual(spec_from_record(spec.to_record()),spec)

    def test_future_contracts_have_explicit_expiry_multiplier_and_settlement(self):
        a=future();b=replace(a,identity=InstrumentIdentity('SYNTHETIC-FUTURES','CONCRETE-2024-10'),
                             last_trade_ms=5000,expiry_ms=6000)
        self.assertNotEqual(a.identity,b.identity)
        self.assertEqual(a.contract_multiplier,D(1000))
        self.assertEqual(spec_from_record(a.to_record()),a)
        self.assertNotEqual(a.fingerprint(),b.fingerprint())

    def test_signed_zero_and_positive_price_domains(self):
        spec=future()
        self.assertEqual(spec.validate_lattice('-12.34','1'),(D('-12.34'),D(1)))
        self.assertEqual(spec.validate_lattice('0','1'),(D(0),D(1)))
        nonnegative=replace(spec,price_domain=PD.NONNEGATIVE)
        with self.assertRaises(ValueError):nonnegative.validate_lattice('-0.01','1')
        nonnegative.validate_lattice('0','1')
        for price in ('0','-1'):
            with self.assertRaises(ValueError):crypto().validate_lattice(price,'0.00002')

    def test_non_power_of_ten_grids_and_minimum_quantity(self):
        spec=crypto()
        self.assertEqual(spec.validate_lattice('123.45','0.00003'),(D('123.45'),D('0.00003')))
        for price,quantity in (('123.46','0.00003'),('123.45','0.00001'),('123.45','0.000025')):
            with self.assertRaises(ValueError):spec.validate_lattice(price,quantity)
        with self.assertRaises(ValueError):replace(spec,minimum_quantity='0.000025')

    def test_metadata_effective_interval_is_half_open_and_not_expiry_admission(self):
        spec=replace(crypto(),effective_until_ms=3000)
        self.assertFalse(spec.effective_at(999));self.assertTrue(spec.effective_at(1000))
        self.assertTrue(spec.effective_at(2999));self.assertFalse(spec.effective_at(3000))
        self.assertTrue(future().effective_at(5000))  # Metadata can remain effective after trading ends.
        for timestamp in (True,-1,1.0):
            with self.assertRaises(ValueError):spec.effective_at(timestamp)

    def test_context_independent_canonical_records_hashes_and_lattices(self):
        a=future();expected=a.fingerprint();record=a.to_record()
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
            self.assertEqual(future().fingerprint(),expected)
            self.assertEqual(spec_from_record(record).fingerprint(),expected)
            self.assertEqual(a.validate_lattice('-123456.78','123456'),(D('-123456.78'),D('123456')))

    def test_numeric_spellings_have_same_canonical_spec(self):
        a=crypto();b=replace(a,contract_multiplier='1.0000',price_step=D('0.0500'))
        self.assertEqual(a.to_record(),b.to_record());self.assertEqual(a.fingerprint(),b.fingerprint())
        self.assertEqual(a.to_record()['price_step'],'0.05')

    def test_immutability(self):
        with self.assertRaises(FrozenInstanceError):crypto().display_symbol='CHANGED'
        with self.assertRaises(FrozenInstanceError):crypto().identity.venue='CHANGED'

    def test_invalid_identity_labels(self):
        for venue,identifier in (('', 'ID'),('VENUE',''),('VENUE','../bad id'),('VENUE','x\n'),
                                 ('V'*65,'ID'),('VENUE',True)):
            with self.assertRaises(ValueError):InstrumentIdentity(venue,identifier)

    def test_enum_type_confusion_and_unsupported_product_asset_pairs(self):
        for name,value in (('asset_class','CRYPTO'),('product','SPOT'),('price_domain','SIGNED'),
                           ('settlement_type','CASH'),('identity',{})):
            with self.assertRaises(ValueError):replace(crypto(),**{name:value})
        for asset,product in ((A.EQUITY,P.SPOT),(A.CRYPTO,P.SHARE),(A.METAL,P.FUND_SHARE),(A.FUND,P.FUTURE)):
            with self.assertRaises(ValueError):replace(crypto(),asset_class=asset,product=product)

    def test_nonfinite_float_bool_negative_and_precision_bounds(self):
        for name in ('contract_multiplier','price_step','quantity_step','minimum_quantity'):
            for value in (True,0.1,'NaN','Infinity','0','-1','1e-13','1e24'):
                with self.assertRaises((ValueError,TypeError)):replace(crypto(),**{name:value})
        for price in (True,0.1,'NaN','Infinity','1e24'):
            with self.assertRaises((ValueError,TypeError)):crypto().validate_lattice(price,'1')

    def test_futures_require_concrete_terms(self):
        for name,value in (('expiry_ms',None),('last_trade_ms',None),('last_trade_ms',5000),
                           ('expiry_ms',True),('last_trade_ms',999),('quantity_unit','SHARE'),
                           ('quantity_step','0.5'),('minimum_quantity','1.5'),
                           ('settlement_type',S.ASSET_DELIVERY),('roll_reference','NOT_APPLICABLE')):
            with self.assertRaises(ValueError):replace(future(),**{name:value})

    def test_nonfutures_do_not_accept_derivative_terms(self):
        for name,value in (('expiry_ms',5000),('last_trade_ms',4000),('contract_multiplier','100'),
                           ('roll_reference','SYNTHETIC-ROLL'),('settlement_type',S.CASH)):
            with self.assertRaises(ValueError):replace(crypto(),**{name:value})

    def test_equity_action_reference_and_non_equity_applicability(self):
        with self.assertRaises(ValueError):replace(crypto(),corporate_action_reference='UNKNOWN-ACTION')
        with self.assertRaises(ValueError):replace(crypto(),asset_class=A.EQUITY,product=P.SHARE,
                                                   settlement_type=S.SECURITY_DELIVERY)

    def test_invalid_metadata_labels_and_dates(self):
        for name,value in (('quote_currency','usd'),('settlement_currency','USD\n'),('source_label',' '),
                           ('quantity_unit',''),('timezone_label','EST'),('calendar_reference','bad calendar'),
                           ('effective_from_ms',True),('observed_at_ms',-1),('expiry_ms',1.5),
                           ('effective_until_ms',1000),('effective_until_ms',253402300800000)):
            with self.assertRaises(ValueError):replace(crypto(),**{name:value})

    def test_record_unknown_missing_types_versions_and_claims_rejected(self):
        base=crypto().to_record()
        cases=[{**base,'extra':1},{k:v for k,v in base.items() if k!='price_unit'},
               {**base,'version':'OTHER'},{**base,'source_independently_authenticated':True},
               {**base,'executable_support_established':1},{**base,'price_step':0.05},
               {**base,'asset_class':A.CRYPTO},{**base,'product':'CFD'},
               {**base,'identity':{**base['identity'],'extra':1}}]
        for record in cases:
            with self.assertRaises((ValueError,TypeError)):spec_from_record(record)
        self.assertEqual(spec_from_record(json.loads(json.dumps(base))),crypto())

    def test_mutating_record_does_not_mutate_frozen_spec(self):
        spec=crypto();before=spec.fingerprint();record=spec.to_record()
        record['identity']['venue']='CHANGED';record['price_step']='1'
        self.assertEqual(spec.fingerprint(),before)
        self.assertIs(spec.to_record()['source_independently_authenticated'],False)
        self.assertIs(spec.to_record()['executable_support_established'],False)

    def test_original_replay_config_is_not_changed_or_generalized(self):
        from ariyan_trading.replay import ReplayConfig,STEP,CENT
        self.assertEqual(STEP,D('0.00000001'));self.assertEqual(CENT,D('0.01'))
        self.assertFalse(hasattr(ReplayConfig(),'instrument'))


if __name__=='__main__':unittest.main()
