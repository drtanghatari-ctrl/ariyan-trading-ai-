"""A012 caller-declared instrument terms; metadata only, no trading authority."""
import hashlib
import json
import re
from dataclasses import dataclass, fields
from decimal import Decimal
from enum import Enum

from .ledger_validation import bounded_decimal

VERSION = 'ARIYAN-A012-INSTRUMENT-SPEC-V1'
MAX_TIMESTAMP_MS = 253402300799999


class AssetClass(Enum):
    CRYPTO = 'CRYPTO'
    EQUITY = 'EQUITY'
    FUND = 'FUND'
    METAL = 'METAL'
    ENERGY = 'ENERGY'


class ProductType(Enum):
    SPOT = 'SPOT'
    SHARE = 'SHARE'
    FUND_SHARE = 'FUND_SHARE'
    FUTURE = 'FUTURE'


class PriceDomain(Enum):
    POSITIVE = 'POSITIVE'
    NONNEGATIVE = 'NONNEGATIVE'
    SIGNED = 'SIGNED'


class SettlementType(Enum):
    ASSET_DELIVERY = 'ASSET_DELIVERY'
    SECURITY_DELIVERY = 'SECURITY_DELIVERY'
    CASH = 'CASH'
    PHYSICAL = 'PHYSICAL'


def _text(value, name, limit=256):
    if (type(value) is not str or not value or value != value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid ' + name)


def _token(value, name, limit=128):
    _text(value, name, limit)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*', value):
        raise ValueError('Invalid ' + name + ' token')


def _timestamp(value, name):
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        raise ValueError('Invalid ' + name)


def _positive(value, name):
    result = Decimal(bounded_decimal(value))
    if result <= 0:
        raise ValueError(name + ' must be positive')
    return result


def _on_grid(value, step):
    # Integer ratios avoid Decimal division/modulo and ambient context rounding.
    vn, vd = value.as_integer_ratio()
    sn, sd = step.as_integer_ratio()
    return (vn * sd) % (vd * sn) == 0


def _decimal_text(value):
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _canonical(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


@dataclass(frozen=True)
class InstrumentIdentity:
    venue: str
    venue_instrument_id: str

    def __post_init__(self):
        _token(self.venue, 'venue', 64)
        _token(self.venue_instrument_id, 'venue_instrument_id')

    def to_record(self):
        return {'venue': self.venue, 'venue_instrument_id': self.venue_instrument_id}

    def fingerprint(self):
        return hashlib.sha256(b'ARIYAN-A012-IDENTITY-V1\0' + _canonical(self.to_record())).hexdigest()


@dataclass(frozen=True)
class InstrumentSpec:
    identity: InstrumentIdentity
    display_symbol: str
    asset_class: AssetClass
    product: ProductType
    underlying_label: str
    quote_currency: str
    settlement_currency: str
    quantity_unit: str
    price_unit: str
    contract_multiplier: Decimal
    price_step: Decimal
    quantity_step: Decimal
    minimum_quantity: Decimal
    price_domain: PriceDomain
    settlement_type: SettlementType
    calendar_reference: str
    timezone_label: str
    corporate_action_reference: str
    roll_reference: str
    effective_from_ms: int
    effective_until_ms: int | None
    last_trade_ms: int | None
    expiry_ms: int | None
    source_label: str
    observed_at_ms: int

    def __post_init__(self):
        if type(self.identity) is not InstrumentIdentity:
            raise ValueError('InstrumentIdentity required')
        for name, kind in (('asset_class', AssetClass), ('product', ProductType),
                           ('price_domain', PriceDomain), ('settlement_type', SettlementType)):
            if type(getattr(self, name)) is not kind:
                raise ValueError(name + ' enum required')
        _text(self.display_symbol, 'display_symbol', 80)
        _text(self.underlying_label, 'underlying_label')
        for name in ('quote_currency', 'settlement_currency'):
            value = getattr(self, name)
            _token(value, name, 24)
            if value != value.upper():
                raise ValueError(name + ' must be an uppercase caller label')
        for name in ('quantity_unit', 'price_unit', 'calendar_reference',
                     'corporate_action_reference', 'roll_reference'):
            _token(getattr(self, name), name)
        _token(self.timezone_label, 'timezone_label', 80)
        if self.timezone_label != 'UTC' and '/' not in self.timezone_label:
            raise ValueError('Use UTC or a region/name timezone label; no fixed abbreviation')
        _text(self.source_label, 'source_label', 2048)
        for name in ('contract_multiplier', 'price_step', 'quantity_step', 'minimum_quantity'):
            object.__setattr__(self, name, _positive(getattr(self, name), name))
        if not _on_grid(self.minimum_quantity, self.quantity_step):
            raise ValueError('Minimum quantity must align to quantity step')
        _timestamp(self.effective_from_ms, 'effective_from_ms')
        _timestamp(self.observed_at_ms, 'observed_at_ms')
        if self.effective_until_ms is not None:
            _timestamp(self.effective_until_ms, 'effective_until_ms')
            if self.effective_until_ms <= self.effective_from_ms:
                raise ValueError('Effective interval must be nonempty and half open')
        allowed = {
            ProductType.SPOT: {AssetClass.CRYPTO, AssetClass.METAL, AssetClass.ENERGY},
            ProductType.SHARE: {AssetClass.EQUITY},
            ProductType.FUND_SHARE: {AssetClass.FUND},
            ProductType.FUTURE: {AssetClass.CRYPTO, AssetClass.EQUITY, AssetClass.METAL, AssetClass.ENERGY},
        }
        if self.asset_class not in allowed[self.product]:
            raise ValueError('Unsupported product/asset-class combination')
        if self.product is ProductType.FUTURE:
            _timestamp(self.last_trade_ms, 'last_trade_ms')
            _timestamp(self.expiry_ms, 'expiry_ms')
            if not self.effective_from_ms <= self.last_trade_ms <= self.expiry_ms:
                raise ValueError('Future requires effective start <= last trade <= expiry')
            if self.settlement_type not in (SettlementType.CASH, SettlementType.PHYSICAL):
                raise ValueError('Future requires explicit cash or physical settlement')
            if self.quantity_unit != 'CONTRACT' or self.roll_reference == 'NOT_APPLICABLE':
                raise ValueError('Future requires CONTRACT quantities and an explicit roll reference')
            if (self.quantity_step != self.quantity_step.to_integral_value()
                    or self.minimum_quantity != self.minimum_quantity.to_integral_value()):
                raise ValueError('A012 futures support whole-contract quantity grids only')
        else:
            if self.expiry_ms is not None or self.last_trade_ms is not None:
                raise ValueError('Expiry/last-trade fields are reserved for concrete futures')
            if self.roll_reference != 'NOT_APPLICABLE' or self.contract_multiplier != 1:
                raise ValueError('Non-futures require multiplier 1 and no roll policy')
            expected = SettlementType.ASSET_DELIVERY if self.product is ProductType.SPOT else SettlementType.SECURITY_DELIVERY
            if self.settlement_type is not expected:
                raise ValueError('Settlement type inconsistent with product')
            if self.product in (ProductType.SHARE, ProductType.FUND_SHARE) and self.quantity_unit != 'SHARE':
                raise ValueError('Share products require quantities in SHARE units')
        if self.asset_class in (AssetClass.EQUITY, AssetClass.FUND):
            if self.corporate_action_reference == 'NOT_APPLICABLE':
                raise ValueError('Equity/fund exposure requires explicit corporate-action reference')
        elif self.corporate_action_reference != 'NOT_APPLICABLE':
            raise ValueError('A012 non-equity instruments require no corporate-action policy')

    def validate_lattice(self, price, quantity):
        """Check declared zero-origin grids/domain only; never an order admission decision."""
        price = Decimal(bounded_decimal(price))
        quantity = _positive(quantity, 'quantity')
        if (self.price_domain is PriceDomain.POSITIVE and price <= 0
                or self.price_domain is PriceDomain.NONNEGATIVE and price < 0):
            raise ValueError('Price outside declared domain')
        if quantity < self.minimum_quantity or not _on_grid(quantity, self.quantity_step):
            raise ValueError('Quantity outside declared minimum/grid')
        if not _on_grid(price, self.price_step):
            raise ValueError('Price outside declared grid')
        return price, quantity

    def effective_at(self, timestamp_ms):
        """Metadata effective interval only; says nothing about sessions/expiry/admission."""
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
        return hashlib.sha256(b'ARIYAN-A012-SPEC-V1\0' + _canonical(self.to_record())).hexdigest()


def spec_from_record(record):
    if type(record) is not dict:
        raise ValueError('Instrument record object required')
    metadata = {'version', 'source_independently_authenticated', 'executable_support_established'}
    if set(record) != {f.name for f in fields(InstrumentSpec)} | metadata:
        raise ValueError('Missing or unknown instrument record fields')
    if (record['version'] != VERSION or record['source_independently_authenticated'] is not False
            or record['executable_support_established'] is not False):
        raise ValueError('Unsupported schema or authenticity/execution claim')
    values = {f.name: record[f.name] for f in fields(InstrumentSpec)}
    identity = values['identity']
    if type(identity) is not dict or set(identity) != {'venue', 'venue_instrument_id'}:
        raise ValueError('Exact identity record required')
    values['identity'] = InstrumentIdentity(**identity)
    for name, kind in (('asset_class', AssetClass), ('product', ProductType),
                       ('price_domain', PriceDomain), ('settlement_type', SettlementType)):
        if type(values[name]) is not str:
            raise ValueError('Enum record values must be strings')
        values[name] = kind(values[name])
    for name in ('contract_multiplier', 'price_step', 'quantity_step', 'minimum_quantity'):
        if type(values[name]) is not str:
            raise ValueError('Record decimals must be strings')
    return InstrumentSpec(**values)
