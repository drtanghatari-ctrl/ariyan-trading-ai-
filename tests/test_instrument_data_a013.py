"""Synthetic bindings plus one real-data integration fixture; no market assessment."""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal as D, Inexact, Rounded, ROUND_UP, localcontext
from pathlib import Path
from unittest.mock import patch

from symlink_fixture import symlink_or_skip

from ariyan_trading.instruments import (
    InstrumentIdentity, InstrumentSpec, AssetClass as A, ProductType as P,
    PriceDomain as PD, SettlementType as S,
)
from ariyan_trading.instrument_data import (
    PRICE_BASIS, build_instrument_binding, verify_instrument_binding,
    read_instrument_binding, write_instrument_binding,
)
from ariyan_trading.market_data import Candle, CandleDataset, load_candles

ROOT=Path(__file__).resolve().parents[1]


def dataset():
    bars=tuple(Candle(i*1000,D('10.00'),D('10.10'),D('9.95'),D('10.05'),D('0.003')) for i in range(3))
    return CandleDataset(bars,'SYNTH',1000,'SYNTHETIC DATA ONLY',3000,'0'*64,'canonical','ms')


def spec():
    return InstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-VENUE','PAIR-1'),display_symbol='OTHER/DISPLAY',
        asset_class=A.CRYPTO,product=P.SPOT,underlying_label='SYNTHETIC ONLY',
        quote_currency='USD',settlement_currency='USD',quantity_unit='TEST_UNIT',price_unit='USD_PER_TEST_UNIT',
        contract_multiplier='1',price_step='0.05',quantity_step='1',minimum_quantity='1',
        price_domain=PD.POSITIVE,settlement_type=S.ASSET_DELIVERY,calendar_reference='SYNTHETIC-24X7',
        timezone_label='UTC',corporate_action_reference='NOT_APPLICABLE',roll_reference='NOT_APPLICABLE',
        effective_from_ms=0,effective_until_ms=3000,last_trade_ms=None,expiry_ms=None,
        source_label='SYNTHETIC TERMS ONLY',observed_at_ms=5000)


def build(data=None,terms=None,**changes):
    kwargs={'expected_symbol':'SYNTH','price_basis':PRICE_BASIS,'volume_unit':'TEST_UNIT',
            'binding_source':'SYNTHETIC CALLER MAPPING ONLY'}
    kwargs.update(changes)
    return build_instrument_binding(data or dataset(),terms or spec(),**kwargs)


class InstrumentDataA013Tests(unittest.TestCase):
    def test_complete_binding_roundtrip_and_false_claims(self):
        binding=build()
        self.assertEqual(verify_instrument_binding(dataset(),spec(),binding),binding)
        self.assertEqual(binding['instrument_identity_sha256'],spec().identity.fingerprint())
        for name in ('source_independently_authenticated','calendar_sessions_verified',
                     'corporate_actions_verified','runtime_binding_enforced',
                     'executable_support_established','live_authorized'):
            self.assertIs(binding[name],False)

    def test_no_symbol_inference_explicit_mapping_required(self):
        self.assertNotEqual(dataset().symbol,spec().display_symbol)
        build()  # Distinct labels can only be linked through the explicit caller assertion.
        for value in ('OTHER',True,None):
            with self.assertRaises(ValueError):build(expected_symbol=value)

    def test_wrong_venue_or_contract_terms_rejected_on_verification(self):
        binding=build()
        for terms in (replace(spec(),identity=InstrumentIdentity('OTHER-VENUE','PAIR-1')),
                      replace(spec(),price_step='0.01'),replace(spec(),source_label='OTHER SOURCE')):
            with self.assertRaises(ValueError):verify_instrument_binding(dataset(),terms,binding)

    def test_subset_content_is_distinct_even_with_parent_raw_hash(self):
        data=dataset();subset=replace(data,candles=data.candles[:2])
        full=build(data);part=build(subset)
        self.assertEqual(full['dataset']['recorded_raw_sha256'],part['dataset']['recorded_raw_sha256'])
        self.assertNotEqual(full['dataset']['candle_content_sha256'],part['dataset']['candle_content_sha256'])
        self.assertIn('PARENT',part['dataset']['recorded_raw_hash_scope'])
        with self.assertRaises(ValueError):verify_instrument_binding(subset,spec(),full)

    def test_changed_values_with_same_raw_hash_are_detected(self):
        data=dataset();bars=list(data.candles);bars[1]=replace(bars[1],close=D('10.10'))
        altered=replace(data,candles=tuple(bars))
        self.assertEqual(data.raw_sha256,altered.raw_sha256)
        self.assertNotEqual(build(data)['dataset']['candle_content_sha256'],build(altered)['dataset']['candle_content_sha256'])
        with self.assertRaises(ValueError):verify_instrument_binding(altered,spec(),build(data))

    def test_canonical_decimal_spellings_and_zero_volume(self):
        data=dataset();bars=tuple(replace(b,open=D('10'),volume=D('0.0030')) for b in data.candles)
        self.assertEqual(build(data),build(replace(data,candles=bars)))
        zero=replace(data,candles=tuple(replace(b,volume=D('0.00')) for b in data.candles))
        minuszero=replace(data,candles=tuple(replace(b,volume=D('-0')) for b in data.candles))
        self.assertEqual(build(zero),build(minuszero))

    def test_metadata_changes_detected_even_with_same_candles(self):
        data=dataset();binding=build(data)
        for altered in (replace(data,source='OTHER SOURCE'),replace(data,as_of_ms=4000),
                        replace(data,raw_sha256='1'*64),replace(data,input_format='binance-spot')):
            self.assertEqual(build(altered)['dataset']['candle_content_sha256'],binding['dataset']['candle_content_sha256'])
            with self.assertRaises(ValueError):verify_instrument_binding(altered,spec(),binding)

    def test_effective_boundaries_cover_complete_bar_intervals(self):
        build(terms=replace(spec(),effective_until_ms=3000))
        for terms in (replace(spec(),effective_from_ms=1),replace(spec(),effective_until_ms=2999)):
            with self.assertRaises(ValueError):build(terms=terms)

    def test_raw_futures_respect_last_trade_and_preserve_multiplier(self):
        terms=replace(spec(),identity=InstrumentIdentity('SYNTHETIC-FUTURES','CONTRACT-1'),
            asset_class=A.ENERGY,product=P.FUTURE,quantity_unit='CONTRACT',contract_multiplier='1000',
            price_unit='USD_PER_BARREL',settlement_type=S.CASH,roll_reference='SYNTHETIC-NO-AUTO-ROLL',
            last_trade_ms=3000,expiry_ms=4000)
        b=build(terms=terms,volume_unit='CONTRACT')
        self.assertEqual(b['instrument']['contract_multiplier'],'1000')
        with self.assertRaises(ValueError):build(terms=replace(terms,last_trade_ms=2999),volume_unit='CONTRACT')

    def test_all_ohlc_fields_must_fit_declared_price_grid(self):
        data=dataset()
        values={'open':'10.01','high':'10.11','low':'9.94','close':'10.06'}
        for name,value in values.items():
            bars=list(data.candles);bars[1]=replace(bars[1],**{name:D(value)})
            with self.assertRaises(ValueError):build(replace(data,candles=tuple(bars)))

    def test_aggregate_volume_is_not_order_minimum_or_lot_size(self):
        # 0.003 volume is below the quantity minimum 1 and off its unit grid.
        self.assertEqual(build()['declaration']['volume_unit'],'TEST_UNIT')
        with self.assertRaises(ValueError):spec().validate_lattice('10','0.003')

    def test_unsupported_adjusted_series_units_and_type_confusion(self):
        for changes in ({'price_basis':'ADJUSTED'},{'price_basis':'CONTINUOUS_FUTURE'},
                        {'volume_unit':'QUOTE_NOT_QUANTITY_UNITS'},{'volume_unit':True},
                        {'binding_source':' '},{'binding_source':'bad\nlabel'}):
            with self.assertRaises(ValueError):build(**changes)
        with self.assertRaises(ValueError):build_instrument_binding({},spec(),expected_symbol='SYNTH',
            price_basis=PRICE_BASIS,volume_unit='TEST_UNIT',binding_source='label')

    def test_schema_tampering_missing_extra_and_authority_claims(self):
        base=build()
        cases=[{**base,'extra':1},{**base,'live_authorized':True},{**base,'live_authorized':0},
               {**base,'binding_sha256':'0'*64},{**base,'version':'OTHER'},
               {k:v for k,v in base.items() if k!='instrument'}]
        other=copy.deepcopy(base);other['dataset']['candles']=True;cases.append(other)
        other=copy.deepcopy(base);other['instrument']['source_independently_authenticated']=True;cases.append(other)
        for case in cases:
            with self.assertRaises(ValueError):verify_instrument_binding(dataset(),spec(),case)

    def test_strict_bounded_json_reader(self):
        import ariyan_trading.instrument_data as module
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bad.json'
            for text in ('{"x":1,"x":2}','{"x":NaN}','[]','{"x":Infinity}'):
                path.write_text(text)
                with self.assertRaises(ValueError):read_instrument_binding(path)
            path.write_bytes(b'{} ')
            with patch.object(module,'MAX_BINDING_BYTES',2):
                with self.assertRaises(ValueError):read_instrument_binding(path)

    def test_verify_before_write_exclusive_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'binding.json'
            bad={**build(),'live_authorized':True}
            with self.assertRaises(ValueError):write_instrument_binding(path,dataset(),spec(),bad)
            self.assertFalse(path.exists())
            digest=write_instrument_binding(path,dataset(),spec(),build())
            before=path.read_bytes()
            self.assertEqual(digest,build()['binding_sha256'])
            self.assertEqual(read_instrument_binding(path),build())
            with self.assertRaises(FileExistsError):write_instrument_binding(path,dataset(),spec(),build())
            self.assertEqual(path.read_bytes(),before)

    def test_read_and_write_do_not_follow_symlink_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'keep';target.write_text('keep')
            link=root/'link'
            symlink_or_skip(link, target)
            with self.assertRaises(ValueError):read_instrument_binding(link)
            with self.assertRaises(ValueError):write_instrument_binding(link,dataset(),spec(),build())
            self.assertEqual(target.read_text(),'keep')

    def test_write_failure_removes_owned_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'binding.json';original=Path.open
            class Broken:
                def __init__(self,stream):self.stream=stream
                def __enter__(self):return self
                def __exit__(self,*args):self.stream.close()
                def write(self,raw):
                    self.stream.write(raw[:10])
                    raise OSError('Synthetic write interruption')
            def fail(target,*args,**kwargs):
                stream=original(target,*args,**kwargs)
                return Broken(stream) if target==path and args and args[0]=='xb' else stream
            with patch.object(Path,'open',new=fail),self.assertRaisesRegex(OSError,'Synthetic'):
                write_instrument_binding(path,dataset(),spec(),build())
            self.assertFalse(path.exists())

    def test_decimal_context_isolation(self):
        expected=build()
        with localcontext() as ctx:
            ctx.prec=2;ctx.rounding=ROUND_UP;ctx.traps[Inexact]=True;ctx.traps[Rounded]=True
            self.assertEqual(build(),expected)
            self.assertEqual(verify_instrument_binding(dataset(),spec(),expected),expected)

    def test_real_fixture_binding_smoke_only(self):
        data=load_candles(ROOT/'examples/a007/BTCUSDT-1h-2024-01-01.csv',symbol='BTCUSDT',
            interval_ms=3600000,source='Existing real fixture; binding smoke only',as_of_ms=1704153600000,
            input_format='binance-spot',timestamp_unit='ms')
        # These are SYNTHETIC terms/mapping, not an authenticated venue specification.
        terms=replace(spec(),price_step='0.00000001',effective_until_ms=None)
        binding=build(data,terms,expected_symbol='BTCUSDT')
        self.assertEqual(binding['dataset']['candles'],24)
        self.assertEqual(verify_instrument_binding(data,terms,binding),binding)

    def test_original_dataset_and_spec_are_not_modified(self):
        data=dataset();terms=spec();before=terms.to_record();bars=data.candles
        binding=build(data,terms);binding['instrument']['identity']['venue']='CHANGED'
        self.assertEqual(terms.to_record(),before);self.assertIs(data.candles,bars)
        self.assertFalse(hasattr(data,'instrument'))


if __name__=='__main__':unittest.main()
