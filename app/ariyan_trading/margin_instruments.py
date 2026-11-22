"""A033 caller-declared forex and CFD terms; metadata and exact arithmetic only.

This module extends the A012 vocabulary without changing A012. It describes
margined products (forex pairs and CFDs on crypto, equities, indices, metals and
energy) by lot size, pip/tick size, margin rates and shorting. It carries no
trading authority, connects to no broker and converts no currencies.
"""
import hashlib
import re
from dataclasses import dataclass, fields
from decimal import Decimal, Inexact, localcontext
from enum import Enum

from .instruments import (
    InstrumentIdentity, _canonical, _decimal_text, _on_grid, _positive,
    _text, _timestamp, _token,
)

VERSION = 'ARIYAN-A033-MARGIN-INSTRUMENT-SPEC-V1'


class MarginAssetClass(Enum):
    FOREX = 'FOREX'
    CRYPTO = 'CRYPTO'
    EQUITY = 'EQUITY'
    INDEX = 'INDEX'
    METAL = 'METAL'
    ENERGY = 'ENERGY'


class MarginProduct(Enum):
    FX_MARGIN = 'FX_MARGIN'
    CFD = 'CFD'


class Side(Enum):
    LONG = 'LONG'
    SHORT = 'SHORT'


_ALLOWED = {
    MarginProduct.FX_MARGIN: {MarginAssetClass.FOREX},
    MarginProduct.CFD: {MarginAssetClass.CRYPTO, MarginAssetClass.EQUITY,
                        MarginAssetClass.INDEX, MarginAssetClass.METAL,
                        MarginAssetClass.ENERGY},
}
_DECIMALS = ('contract_size', 'lot_step', 'minimum_lot', 'maximum_lot', 'price_step',
             'pip_size', 'initial_margin_rate', 'maintenance_margin_rate')


def _exact(operation):
    """Run Decimal arithmetic at high precision and refuse any silent rounding."""
    with localcontext() as context:
        context.prec = 120
        context.traps[Inexact] = True
        return operation()


@dataclass(frozen=True)
class MarginInstrumentSpec:
    identity: InstrumentIdentity
    display_symbol: str
    asset_class: MarginAssetClass
    product: MarginProduct
    base_label: str
    quote_currency: str
    contract_size: Decimal
    lot_step: Decimal
    minimum_lot: Decimal
    maximum_lot: Decimal
    price_step: Decimal
    pip_size: Decimal
    initial_margin_rate: Decimal
    maintenance_margin_rate: Decimal
    allows_short: bool
    financing_reference: str
    commission_reference: str
    calendar_reference: str
    timezone_label: str
    corporate_action_reference: str
    effective_from_ms: int
    effective_until_ms: int | None
    source_label: str
    observed_at_ms: int

    def __post_init__(self):
        if type(self.identity) is not InstrumentIdentity:
            raise ValueError('InstrumentIdentity required')
        for name, kind in (('asset_class', MarginAssetClass), ('product', MarginProduct)):
            if type(getattr(self, name)) is not kind:
                raise ValueError(name + ' enum required')
        if type(self.allows_short) is not bool:
            raise ValueError('allows_short must be a boolean')
        _text(self.display_symbol, 'display_symbol', 80)
        _text(self.base_label, 'base_label')
        _token(self.quote_currency, 'quote_currency', 24)
        if self.quote_currency != self.quote_currency.upper():
            raise ValueError('quote_currency must be an uppercase caller label')
        for name in ('financing_reference', 'commission_reference', 'calendar_reference',
                     'corporate_action_reference'):
            _token(getattr(self, name), name)
        for name in ('financing_reference', 'commission_reference'):
            if getattr(self, name) == 'NOT_APPLICABLE':
                raise ValueError(name + ' must be explicit for margined products')
        _token(self.timezone_label, 'timezone_label', 80)
        if self.timezone_label != 'UTC' and '/' not in self.timezone_label:
            raise ValueError('Use UTC or a region/name timezone label; no fixed abbreviation')
        _text(self.source_label, 'source_label', 2048)
        for name in _DECIMALS:
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if self.asset_class not in _ALLOWED[self.product]:
            raise ValueError('Unsupported product/asset-class combination')
        if self.asset_class is MarginAssetClass.FOREX:
            for name, value in (('base_label', self.base_label), ('quote_currency', self.quote_currency)):
                if not re.fullmatch(r'[A-Z]{3}', value):
                    raise ValueError('Forex ' + name + ' must be a three-letter currency code')
            if self.base_label == self.quote_currency:
                raise ValueError('Forex base and quote currencies must differ')
        if self.asset_class is MarginAssetClass.EQUITY:
            if self.corporate_action_reference == 'NOT_APPLICABLE':
                raise ValueError('Equity CFDs require explicit corporate-action reference')
        elif self.corporate_action_reference != 'NOT_APPLICABLE':
            raise ValueError('Corporate-action policy applies to equity CFDs only')
        if not (_on_grid(self.minimum_lot, self.lot_step) and _on_grid(self.maximum_lot, self.lot_step)):
            raise ValueError('Minimum and maximum lot must align to lot step')
        if self.maximum_lot < self.minimum_lot:
            raise ValueError('Maximum lot below minimum lot')
        if not _on_grid(self.pip_size, self.price_step):
            raise ValueError('Pip size must be a multiple of the price step')
        if self.initial_margin_rate > 1:
            raise ValueError('Initial margin rate cannot exceed 1 (no leverage below 1:1)')
        if self.maintenance_margin_rate > self.initial_margin_rate:
            raise ValueError('Maintenance margin cannot exceed initial margin')
        _timestamp(self.effective_from_ms, 'effective_from_ms')
        _timestamp(self.observed_at_ms, 'observed_at_ms')
        if self.effective_until_ms is not None:
            _timestamp(self.effective_until_ms, 'effective_until_ms')
            if self.effective_until_ms <= self.effective_from_ms:
                raise ValueError('Effective interval must be nonempty and half open')

    def validate_lattice(self, price, lots):
        """Check price/lot grids only; never an order admission decision."""
        price = _positive(price, 'price')
        lots = _positive(lots, 'lots')
        if not _on_grid(price, self.price_step):
            raise ValueError('Price outside declared grid')
        if not self.minimum_lot <= lots <= self.maximum_lot or not _on_grid(lots, self.lot_step):
            raise ValueError('Lots outside declared minimum/maximum/grid')
        return price, lots

    def pip_value_per_lot(self):
        """Quote-currency value of one pip for one lot; no currency conversion."""
        return _exact(lambda: self.pip_size * self.contract_size)

    def notional(self, price, lots):
        """Position value in quote currency: price x lots x contract size."""
        price, lots = self.validate_lattice(price, lots)
        return _exact(lambda: price * lots * self.contract_size)

    def required_initial_margin(self, price, lots):
        """Initial margin in quote currency; an account-currency conversion is separate work."""
        return _exact(lambda: self.notional(price, lots) * self.initial_margin_rate)

    def required_maintenance_margin(self, price, lots):
        return _exact(lambda: self.notional(price, lots) * self.maintenance_margin_rate)

    def profit_and_loss(self, side, entry_price, exit_price, lots):
        """Gross P/L in quote currency, before spread, commission and financing."""
        if type(side) is not Side:
            raise ValueError('Side enum required')
        if side is Side.SHORT and not self.allows_short:
            raise ValueError('Instrument declares shorting as unavailable')
        entry, lots = self.validate_lattice(entry_price, lots)
        exit_, _ = self.validate_lattice(exit_price, lots)
        move = _exact(lambda: exit_ - entry if side is Side.LONG else entry - exit_)
        return _exact(lambda: move * lots * self.contract_size)

    def effective_at(self, timestamp_ms):
        """Metadata effective interval only; says nothing about sessions or admission."""
        _timestamp(timestamp_ms, 'timestamp_ms')
        return (timestamp_ms >= self.effective_from_ms and
                (self.effective_until_ms is None or timestamp_ms < self.effective_until_ms))

    def to_record(self):
        record = {'version': VERSION, 'source_independently_authenticated': False,
                  'executable_support_established': False}
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is InstrumentIdentity:
                value = value.to_record()
            elif isinstance(value, Enum):
                value = value.value
            elif type(value) is Decimal:
                value = _decimal_text(value)
            record[field.name] = value
        return record

    def fingerprint(self):
        return hashlib.sha256(b'ARIYAN-A033-SPEC-V1\0' + _canonical(self.to_record())).hexdigest()


def margin_spec_from_record(record):
    if type(record) is not dict:
        raise ValueError('Instrument record object required')
    metadata = {'version', 'source_independently_authenticated', 'executable_support_established'}
    if set(record) != {f.name for f in fields(MarginInstrumentSpec)} | metadata:
        raise ValueError('Missing or unknown instrument record fields')
    if (record['version'] != VERSION or record['source_independently_authenticated'] is not False
            or record['executable_support_established'] is not False):
        raise ValueError('Unsupported schema or authenticity/execution claim')
    values = {f.name: record[f.name] for f in fields(MarginInstrumentSpec)}
    identity = values['identity']
    if type(identity) is not dict or set(identity) != {'venue', 'venue_instrument_id'}:
        raise ValueError('Exact identity record required')
    values['identity'] = InstrumentIdentity(**identity)
    for name, kind in (('asset_class', MarginAssetClass), ('product', MarginProduct)):
        if type(values[name]) is not str:
            raise ValueError('Enum record values must be strings')
        values[name] = kind(values[name])
    for name in _DECIMALS:
        if type(values[name]) is not str:
            raise ValueError('Record decimals must be strings')
    return MarginInstrumentSpec(**values)
