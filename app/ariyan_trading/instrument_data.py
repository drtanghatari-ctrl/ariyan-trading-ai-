"""A013 unsigned instrument-to-candle bindings; no market authenticity or authority."""
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from .instruments import InstrumentSpec, PriceDomain, ProductType, MAX_TIMESTAMP_MS
from .market_data import CandleDataset

VERSION = 'ARIYAN-A013-INSTRUMENT-DATA-BINDING-V1'
PRICE_BASIS = 'RAW_UNADJUSTED_SINGLE_INSTRUMENT'
MAX_BINDING_BYTES = 65536


def _encoded(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _text(value):
    if (type(value) is not str or not value or value != value.strip() or len(value) > 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('A nonempty bounded binding-source label is required')


def _number_text(value):
    if value == 0:
        return '0'
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _grid(value, step):
    vn, vd = value.as_integer_ratio()
    sn, sd = step.as_integer_ratio()
    return (vn * sd) % (vd * sn) == 0


def build_instrument_binding(dataset, spec, *, expected_symbol, price_basis,
                             volume_unit, binding_source):
    """Record a caller-declared mapping after checking the supplied rows and terms.

    Does not read original source bytes, infer a venue identity from a symbol,
    resolve calendars/actions, compute performance, or admit orders.
    """
    if type(dataset) is not CandleDataset or type(spec) is not InstrumentSpec:
        raise ValueError('Validated CandleDataset and InstrumentSpec required')
    # Recheck existing invariants. This does not authenticate the objects or source.
    replace(dataset)
    replace(spec)
    if type(expected_symbol) is not str or expected_symbol != dataset.symbol:
        raise ValueError('Explicit dataset symbol does not match supplied dataset')
    if type(price_basis) is not str or price_basis != PRICE_BASIS:
        raise ValueError('Only raw unadjusted single-instrument observations are supported')
    if type(volume_unit) is not str or volume_unit != spec.quantity_unit:
        raise ValueError('Volume must be explicitly declared in instrument quantity units')
    _text(binding_source)
    first = dataset.candles[0].timestamp_ms
    end = dataset.candles[-1].timestamp_ms + dataset.interval_ms
    if not 0 <= first < end <= dataset.as_of_ms <= MAX_TIMESTAMP_MS:
        raise ValueError('Dataset timestamps outside supported range')
    if (first < spec.effective_from_ms
            or spec.effective_until_ms is not None and end > spec.effective_until_ms):
        raise ValueError('One instrument definition must cover every complete candle interval')
    if spec.product is ProductType.FUTURE and end > spec.last_trade_ms:
        raise ValueError('Raw futures observations extend past declared last-trade time')
    content = hashlib.sha256(b'ARIYAN-A013-CANDLE-CONTENT-V1\0')
    content.update(_encoded({'interval_ms': dataset.interval_ms, 'candles': len(dataset.candles)}) + b'\n')
    for bar in dataset.candles:
        replace(bar)
        for name in ('open', 'high', 'low', 'close'):
            value = getattr(bar, name)
            if (spec.price_domain is PriceDomain.POSITIVE and value <= 0
                    or spec.price_domain is PriceDomain.NONNEGATIVE and value < 0
                    or not _grid(value, spec.price_step)):
                raise ValueError('OHLC price outside declared instrument domain/grid')
        # Aggregate volume is not an order quantity: no minimum/order-lot grid check.
        row = [bar.timestamp_ms] + [_number_text(getattr(bar, name))
                                    for name in ('open', 'high', 'low', 'close', 'volume')]
        content.update(_encoded(row) + b'\n')
    record = {
        'version': VERSION,
        'instrument': spec.to_record(),
        'instrument_identity_sha256': spec.identity.fingerprint(),
        'instrument_spec_sha256': spec.fingerprint(),
        'symbol_mapping': {'dataset_symbol': expected_symbol,
                           'status': 'CALLER_DECLARED_NOT_INDEPENDENTLY_VERIFIED'},
        'declaration': {'price_basis': price_basis, 'volume_unit': volume_unit,
                        'binding_source_label': binding_source},
        'dataset': {'symbol': dataset.symbol, 'source_label': dataset.source,
                    'recorded_raw_sha256': dataset.raw_sha256,
                    'recorded_raw_hash_scope': 'CALLER_RECORDED_INPUT_MAY_IDENTIFY_PARENT_BYTES_NOT_SUBSET',
                    'candle_content_sha256': content.hexdigest(),
                    'content_hash_scope': 'CANONICAL_CURRENT_ROWS_AND_INTERVAL_NOT_ORIGINAL_BYTES',
                    'input_format': dataset.input_format, 'timestamp_unit': dataset.timestamp_unit,
                    'interval_ms': dataset.interval_ms, 'as_of_ms': dataset.as_of_ms,
                    'candles': len(dataset.candles), 'first_open_ms': first, 'last_close_ms': end},
        'source_independently_authenticated': False,
        'calendar_sessions_verified': False,
        'corporate_actions_verified': False,
        'runtime_binding_enforced': False,
        'executable_support_established': False,
        'live_authorized': False,
        'limitations': [
            'Unsigned caller declarations and hashes are not venue authenticity, freshness or authority.',
            'Original bytes are not read here; the recorded raw hash is inherited provenance metadata.',
            'Symbols, units, raw-price basis and venue mappings require independent adapter verification.',
            'Calendar/timezone/action/roll labels do not establish implemented or verified policies.',
            'A007 continuous positive-price candles remain required; session gaps and signed candles are not added.',
            'A007/A009/replay remain directly callable; this binding is not an access-control gate.',
            'No performance, liquidity, order admission, accounting, risk or live-readiness approval follows.'],
    }
    record['binding_sha256'] = hashlib.sha256(b'ARIYAN-A013-BINDING-V1\0' + _encoded(record)).hexdigest()
    return record


def verify_instrument_binding(dataset, spec, binding):
    """Rebuild and compare every field, with JSON type-sensitive equality."""
    if type(binding) is not dict:
        raise ValueError('Binding object required')
    try:
        expected = build_instrument_binding(dataset, spec,
            expected_symbol=binding['symbol_mapping']['dataset_symbol'],
            price_basis=binding['declaration']['price_basis'],
            volume_unit=binding['declaration']['volume_unit'],
            binding_source=binding['declaration']['binding_source_label'])
        if _encoded(binding) != _encoded(expected):
            raise ValueError('Binding differs from supplied candles, instrument or supported schema')
    except (KeyError, TypeError, IndexError) as exc:
        raise ValueError('Malformed instrument binding') from exc
    return expected


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _invalid(value):
    raise ValueError('Nonfinite JSON value: ' + value)


def read_instrument_binding(path):
    """Read bounded strict JSON only; call verify_instrument_binding separately."""
    path = Path(path)
    if path.resolve() != path.absolute():
        raise ValueError('Binding symlink paths are not accepted')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BINDING_BYTES + 1)
    if len(raw) > MAX_BINDING_BYTES:
        raise ValueError('Binding exceeds 64 KiB')
    record = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique, parse_constant=_invalid)
    if type(record) is not dict:
        raise ValueError('Binding JSON object required')
    return record


def write_instrument_binding(path, dataset, spec, binding):
    """Verify before exclusive creation; never overwrite an input or previous report."""
    verified = verify_instrument_binding(dataset, spec, binding)
    raw = _encoded(verified) + b'\n'
    if len(raw) > MAX_BINDING_BYTES:
        raise ValueError('Binding exceeds 64 KiB')
    path = Path(path)
    if path.resolve() != path.absolute():
        raise ValueError('Binding symlink paths are not accepted')
    stream = path.open('xb')
    try:
        with stream:
            stream.write(raw)
    except BaseException:
        path.unlink()
        raise
    return verified['binding_sha256']
