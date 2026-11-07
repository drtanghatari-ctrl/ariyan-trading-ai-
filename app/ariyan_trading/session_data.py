"""A015 offline canonical candle intake against declared instrument/session terms."""
import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

from .instruments import InstrumentSpec, ProductType, PriceDomain
from .instrument_data import PRICE_BASIS, _grid, _number_text
from .market_data import Candle, HEADER, MAX_BYTES, MAX_ROWS, _timestamp, number
from .sessions import SessionSchedule, assess_observation_times, schedule_from_record

VERSION = 'ARIYAN-A015-SESSION-CANDLE-INTAKE-V1'


def _encoded(record):
    return json.dumps(record, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def _label(value, name):
    if (type(value) is not str or not value or value != value.strip() or len(value) > 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Invalid ' + name)


def _request(spec, schedule, symbol, source, price_basis, volume_unit, mapping_source,
             interval_ms, anchor_ms, first_open_ms, end_exclusive_ms, as_of_ms, opens):
    if type(spec) is not InstrumentSpec or type(schedule) is not SessionSchedule:
        raise ValueError('InstrumentSpec and SessionSchedule required')
    replace(spec)
    # Reconstruction validates every window, including ones outside the query.
    schedule = schedule_from_record(schedule.to_record())
    if (spec.calendar_reference != schedule.schedule_id
            or spec.timezone_label != schedule.timezone_label):
        raise ValueError('Declared calendar ID/timezone must match instrument references')
    if type(symbol) is not str or not re.fullmatch(r'[A-Z0-9][A-Z0-9_.:/-]{0,39}', symbol):
        raise ValueError('Invalid caller-declared dataset symbol')
    _label(source, 'source label'); _label(mapping_source, 'mapping-source label')
    if type(price_basis) is not str or price_basis != PRICE_BASIS:
        raise ValueError('Only raw unadjusted single-instrument price basis is supported')
    if type(volume_unit) is not str or volume_unit != spec.quantity_unit:
        raise ValueError('Explicit volume unit must match instrument quantity units')
    assessment = assess_observation_times(schedule, opens, interval_ms=interval_ms,
        anchor_ms=anchor_ms, first_open_ms=first_open_ms, end_exclusive_ms=end_exclusive_ms, as_of_ms=as_of_ms)
    if (first_open_ms < spec.effective_from_ms
            or spec.effective_until_ms is not None and end_exclusive_ms > spec.effective_until_ms):
        raise ValueError('One specification must cover the entire requested interval')
    if spec.product is ProductType.FUTURE and end_exclusive_ms > spec.last_trade_ms:
        raise ValueError('Requested raw futures interval extends beyond declared last trade')
    return assessment


@dataclass(frozen=True)
class SessionCandleSeries:
    candles: tuple
    symbol: str
    source: str
    raw_sha256: str
    spec: InstrumentSpec
    schedule: SessionSchedule
    interval_ms: int
    anchor_ms: int
    first_open_ms: int
    end_exclusive_ms: int
    as_of_ms: int
    price_basis: str
    volume_unit: str
    mapping_source: str

    def __post_init__(self):
        self.to_report()

    def to_report(self):
        if type(self.candles) is not tuple or len(self.candles) > MAX_ROWS:
            raise ValueError('Bounded candle tuple required; empty input is permitted')
        if type(self.raw_sha256) is not str or not re.fullmatch(r'[0-9a-f]{64}', self.raw_sha256):
            raise ValueError('Recorded source SHA-256 required')
        for bar in self.candles:
            if type(bar) is not Candle:
                raise ValueError('Exact validated Candle objects required')
            replace(bar)
        assessment = _request(self.spec,self.schedule,self.symbol,self.source,self.price_basis,
            self.volume_unit,self.mapping_source,self.interval_ms,self.anchor_ms,self.first_open_ms,
            self.end_exclusive_ms,self.as_of_ms,tuple(b.timestamp_ms for b in self.candles))
        content = hashlib.sha256(b'ARIYAN-A015-CANDLE-CONTENT-V1\0')
        content.update(_encoded({'interval_ms':self.interval_ms,'candles':len(self.candles)}) + b'\n')
        for bar in self.candles:
            for name in ('open','high','low','close'):
                value = getattr(bar,name)
                if (self.spec.price_domain is PriceDomain.POSITIVE and value <= 0
                        or self.spec.price_domain is PriceDomain.NONNEGATIVE and value < 0
                        or not _grid(value,self.spec.price_step)):
                    raise ValueError('OHLC price outside declared instrument domain/grid')
            row = [bar.timestamp_ms] + [_number_text(getattr(bar,n)) for n in ('open','high','low','close','volume')]
            content.update(_encoded(row) + b'\n')
        report = {'version':VERSION,'symbol_mapping':{'dataset_symbol':self.symbol,
                    'mapping_source_label':self.mapping_source,'status':'CALLER_DECLARED_UNVERIFIED'},
            'instrument':self.spec.to_record(),'instrument_identity_sha256':self.spec.identity.fingerprint(),
            'instrument_spec_sha256':self.spec.fingerprint(),
            'source':{'label':self.source,'input_format':'canonical','timestamp_unit':'ms',
                      'recorded_raw_sha256':self.raw_sha256,
                      'raw_hash_scope':'RECORDED_FULL_INPUT_BYTES_MAY_IDENTIFY_PARENT_FOR_SUBSETS_MANUAL_VALUES_ARE_CALLER_ASSERTIONS'},
            'declaration':{'price_basis':self.price_basis,'volume_unit':self.volume_unit},
            'candles':len(self.candles),'canonical_candle_content_sha256':content.hexdigest(),
            'content_hash_scope':'ALL_SUPPLIED_CANONICAL_ROWS_AND_INTERVAL_NOT_SOURCE_BYTES',
            'row_validation':'POSITIVE_OHLC_NONNEGATIVE_VOLUME_AND_DECLARED_PRICE_GRID_ONLY',
            'session_assessment':assessment,
            'declared_calendar_references_match':True,
            'source_independently_authenticated':False,'instrument_mapping_independently_verified':False,
            'calendar_independently_verified':False,'point_in_time_availability_established':False,
            'session_aware_replay_available':False,'live_authorized':False,
            'limitations':[
                'Venue, raw basis, units, exhaustive schedule and mapping remain unsigned caller assertions.',
                'Reference-label equality is not independent exchange-calendar or instrument verification.',
                'All valid supplied rows are retained, including observations outside full declared sessions.',
                'Absent session bars, closures, unknowns and boundary intervals remain distinct; no repairs.',
                'Presence and basic OHLCV checks do not prove liquidity, source truth, freshness or fillability.',
                'Current parser requires positive OHLC prices; signed/zero price candles are not supported.',
                'No timezone conversion, holiday/halt discovery, corporate actions, roll or PnL implementation.',
                'A007 replay rejects this distinct series type; no session-aware simulation or trade authority.']}
        report['intake_sha256'] = hashlib.sha256(b'ARIYAN-A015-INTAKE-V1\0' + _encoded(report)).hexdigest()
        return report


def load_session_candles(path, *, symbol, source, spec, schedule, interval_ms, anchor_ms,
                         first_open_ms, end_exclusive_ms, as_of_ms, price_basis,
                         volume_unit, mapping_source):
    """Load bounded six-column canonical CSV once; preserve all timestamps and rows.

    Gaps are assessed, not repaired. Any malformed row rejects the entire file.
    Header-only input is retained as an empty series with explicit missing times.
    """
    _request(spec,schedule,symbol,source,price_basis,volume_unit,mapping_source,interval_ms,
             anchor_ms,first_open_ms,end_exclusive_ms,as_of_ms,())
    path = Path(path)
    if path.resolve() != path.absolute():
        raise ValueError('Symlink input paths are not accepted')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('CSV exceeds 32 MiB')
    reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
    if next(reader,None) != HEADER:
        raise ValueError('Exact canonical six-column header required')
    candles = []
    try:
        for row in reader:
            if len(candles) >= MAX_ROWS or len(row) != 6:
                raise ValueError('CSV candle count or column count outside bounds')
            values = [field.strip() for field in row]
            opened = _timestamp(values[0])
            numbers = [number(value,name,allow_zero=(name=='volume'))
                       for value,name in zip(values[1:],HEADER[1:])]
            candles.append(Candle(opened,*numbers))
    except (ValueError,TypeError,csv.Error) as exc:
        raise ValueError(f'CSV line {reader.line_num}: {exc}') from exc
    return SessionCandleSeries(tuple(candles),symbol,source,hashlib.sha256(raw).hexdigest(),
        spec,schedule,interval_ms,anchor_ms,first_open_ms,end_exclusive_ms,as_of_ms,
        price_basis,volume_unit,mapping_source)


def verify_session_report(series, report):
    """Compare every field against supplied series/declarations; no authenticity claim."""
    if type(series) is not SessionCandleSeries or type(report) is not dict:
        raise ValueError('SessionCandleSeries and report object required')
    expected = series.to_report()
    if _encoded(report) != _encoded(expected):
        raise ValueError('Report differs from supplied series or supported schema')
    return expected
