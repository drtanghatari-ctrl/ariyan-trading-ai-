"""Synthetic forex/CFD terms only; no real broker specifications or prices."""
import copy
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal as D, localcontext

from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginProduct as P, MarginInstrumentSpec, Side,
    margin_spec_from_record,
)


def forex():
    return MarginInstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'FX-PAIR-001'),
        display_symbol='EURUSD', asset_class=A.FOREX, product=P.FX_MARGIN,
        base_label='EUR', quote_currency='USD', contract_size='100000',
        lot_step='0.01', minimum_lot='0.01', maximum_lot='100', price_step='0.00001',
        pip_size='0.0001', initial_margin_rate='0.01', maintenance_margin_rate='0.005',
        allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-FX-WEEK-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=1000, effective_until_ms=None,
        source_label='SYNTHETIC TEST ONLY; not real broker terms', observed_at_ms=2000)


def cfd(asset=A.METAL, **changes):
    terms = dict(identity=InstrumentIdentity('SYNTHETIC-BROKER', 'CFD-001'),
                 display_symbol='SYNTH-CFD', asset_class=asset, product=P.CFD,
                 base_label='SYNTHETIC underlying', quote_currency='USD', contract_size='100',
                 lot_step='0.01', minimum_lot='0.01', maximum_lot='50', price_step='0.01',
                 pip_size='0.1', initial_margin_rate='0.05', maintenance_margin_rate='0.025')
    terms.update(changes)
    return replace(forex(), **terms)


class MarginInstrumentsA033Tests(unittest.TestCase):
    def test_forex_pip_value_notional_and_margin_are_exact(self):
        spec = forex()
        self.assertEqual(spec.pip_value_per_lot(), D(10))
        self.assertEqual(spec.notional('1.10000', '1'), D(110000))
        self.assertEqual(spec.required_initial_margin('1.10000', '1'), D(1100))
        self.assertEqual(spec.required_maintenance_margin('1.10000', '1'), D(550))
        self.assertEqual(spec.required_initial_margin('1.12345', '0.05'), D('56.1725'))

    def test_profit_and_loss_long_and_short(self):
        spec = forex()
        self.assertEqual(spec.profit_and_loss(Side.LONG, '1.10000', '1.10500', '1'), D(500))
        self.assertEqual(spec.profit_and_loss(Side.SHORT, '1.10000', '1.10500', '1'), D(-500))
        self.assertEqual(spec.profit_and_loss(Side.SHORT, '1.10000', '1.09000', '0.5'), D(500))
        self.assertEqual(spec.profit_and_loss(Side.LONG, '1.10000', '1.10000', '1'), D(0))

    def test_shorting_can_be_declared_unavailable(self):
        spec = cfd(A.EQUITY, allows_short=False, corporate_action_reference='SYNTHETIC-ACTIONS-V1')
        self.assertEqual(spec.profit_and_loss(Side.LONG, '10.00', '11.00', '1'), D(100))
        with self.assertRaises(ValueError):
            spec.profit_and_loss(Side.SHORT, '10.00', '11.00', '1')
        with self.assertRaises(ValueError):
            spec.profit_and_loss('LONG', '10.00', '11.00', '1')

    def test_every_asset_class_round_trips_through_records(self):
        specs = [forex(), cfd(A.CRYPTO), cfd(A.INDEX), cfd(A.METAL), cfd(A.ENERGY),
                 cfd(A.EQUITY, corporate_action_reference='SYNTHETIC-ACTIONS-V1')]
        for spec in specs:
            record = json.loads(json.dumps(spec.to_record()))
            self.assertEqual(margin_spec_from_record(record), spec)
            self.assertFalse(record['executable_support_established'])
            self.assertFalse(record['source_independently_authenticated'])

    def test_lattice_checks_price_lots_and_bounds(self):
        spec = forex()
        self.assertEqual(spec.validate_lattice('1.23456', '0.07'), (D('1.23456'), D('0.07')))
        for price, lots in (('1.234567', '1'), ('1.2', '0.005'), ('1.2', '0.001'),
                            ('1.2', '100.01'), ('0', '1'), ('-1', '1'), ('1.2', '0')):
            with self.assertRaises(ValueError):
                spec.validate_lattice(price, lots)
        for bad in (1.1, True, float('nan'), 'abc'):
            with self.assertRaises((ValueError, TypeError)):
                spec.validate_lattice(bad, '1')

    def test_arithmetic_ignores_ambient_decimal_context(self):
        spec = forex()
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(spec.required_initial_margin('1.12345', '0.05'), D('56.1725'))
            self.assertEqual(spec.profit_and_loss(Side.LONG, '1.00001', '1.12345', '0.03'), D('370.32'))

    def test_invalid_product_and_asset_class_combinations(self):
        with self.assertRaises(ValueError):
            replace(forex(), asset_class=A.CRYPTO)
        with self.assertRaises(ValueError):
            replace(cfd(), asset_class=A.FOREX)
        with self.assertRaises(ValueError):
            replace(forex(), asset_class='FOREX')
        with self.assertRaises(ValueError):
            replace(forex(), product='FX_MARGIN')

    def test_forex_currency_codes(self):
        for field, value in (('base_label', 'EURO'), ('base_label', 'eur'), ('quote_currency', 'US'),
                             ('base_label', 'USD')):
            with self.assertRaises(ValueError):
                replace(forex(), **{field: value})

    def test_margin_rate_rules(self):
        for changes in ({'initial_margin_rate': '1.01'}, {'initial_margin_rate': '0'},
                        {'maintenance_margin_rate': '0.02'}, {'maintenance_margin_rate': '-0.1'}):
            with self.assertRaises(ValueError):
                replace(forex(), **changes)
        self.assertEqual(replace(forex(), initial_margin_rate='1',
                                 maintenance_margin_rate='1').required_initial_margin('2', '1'), D(200000))

    def test_lot_and_pip_grid_rules(self):
        for changes in ({'minimum_lot': '0.005'}, {'maximum_lot': '100.005'},
                        {'maximum_lot': '0.001', 'minimum_lot': '0.01'}, {'pip_size': '0.000015'},
                        {'lot_step': '0'}, {'contract_size': '0'}):
            with self.assertRaises(ValueError):
                replace(forex(), **changes)

    def test_references_and_flags_must_be_explicit(self):
        for changes in ({'financing_reference': 'NOT_APPLICABLE'},
                        {'commission_reference': 'NOT_APPLICABLE'},
                        {'financing_reference': ''}, {'allows_short': 'yes'}, {'allows_short': 1},
                        {'timezone_label': 'EST'}, {'quote_currency': 'usd'},
                        {'effective_until_ms': 1000}, {'observed_at_ms': -1}):
            with self.assertRaises(ValueError):
                replace(forex(), **changes)

    def test_corporate_action_policy_only_for_equity_cfds(self):
        with self.assertRaises(ValueError):
            cfd(A.EQUITY, corporate_action_reference="NOT_APPLICABLE")
        with self.assertRaises(ValueError):
            cfd(A.METAL, corporate_action_reference='SYNTHETIC-ACTIONS-V1')
        with self.assertRaises(ValueError):
            replace(forex(), corporate_action_reference='SYNTHETIC-ACTIONS-V1')

    def test_effective_interval(self):
        spec = replace(forex(), effective_until_ms=5000)
        self.assertFalse(spec.effective_at(999))
        self.assertTrue(spec.effective_at(1000))
        self.assertTrue(spec.effective_at(4999))
        self.assertFalse(spec.effective_at(5000))
        self.assertTrue(forex().effective_at(253402300799999))

    def test_fingerprint_is_canonical_and_sensitive(self):
        a, b = forex(), replace(forex(), contract_size='100000.0')
        self.assertEqual(a.fingerprint(), b.fingerprint())
        self.assertNotEqual(a.fingerprint(), replace(a, display_symbol='EUR/USD').fingerprint())
        self.assertNotEqual(a.fingerprint(), replace(a, initial_margin_rate='0.02').fingerprint())
        self.assertNotEqual(a.fingerprint(), cfd().fingerprint())
        self.assertEqual(len(a.fingerprint()), 64)

    def test_instances_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            forex().allows_short = False

    def test_record_schema_is_strict(self):
        record = forex().to_record()
        broken = []
        for key in record:
            missing = copy.deepcopy(record)
            del missing[key]
            broken.append(missing)
        extra = copy.deepcopy(record)
        extra['unexpected'] = 1
        broken.append(extra)
        for key, value in (('version', 'ARIYAN-A033-MARGIN-INSTRUMENT-SPEC-V2'),
                           ('executable_support_established', True),
                           ('source_independently_authenticated', True),
                           ('asset_class', 'STOCKS'), ('asset_class', 1),
                           ('contract_size', 100000), ('lot_step', 0.01),
                           ('identity', {'venue': 'X'}), ('allows_short', 'true')):
            changed = copy.deepcopy(record)
            changed[key] = value
            broken.append(changed)
        for item in broken:
            with self.assertRaises((ValueError, TypeError, KeyError)):
                margin_spec_from_record(item)
        with self.assertRaises(ValueError):
            margin_spec_from_record([record])

    def test_a012_remains_unchanged_and_does_not_accept_these_products(self):
        from ariyan_trading import instruments
        self.assertEqual(instruments.VERSION, 'ARIYAN-A012-INSTRUMENT-SPEC-V1')
        self.assertFalse(hasattr(instruments.AssetClass, 'FOREX'))
        self.assertFalse(hasattr(instruments.ProductType, 'CFD'))


if __name__ == '__main__':
    unittest.main()
