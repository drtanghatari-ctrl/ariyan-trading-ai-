"""A011 offline historical quality index. Quarantines rows; never repairs gaps."""
import argparse
import csv
import hashlib
import io
import json
import re
from dataclasses import asdict,dataclass
from pathlib import Path

from .market_data import Candle,CandleDataset,MAX_BYTES,MAX_ROWS,integer,number


@dataclass(frozen=True)
class ExcludedRow:
    line: int
    open_ms: int
    reasons: tuple
    published_close_raw: str
    expected_close_raw: int


@dataclass(frozen=True)
class MissingInterval:
    first_missing_open_ms: int
    end_exclusive_ms: int
    missing_rows: int


@dataclass(frozen=True)
class CompleteSpan:
    start_index: int
    end_index_exclusive: int
    first_open_ms: int
    last_close_ms: int


@dataclass(frozen=True)
class HistoryIndex:
    candles: tuple
    spans: tuple
    exclusions: tuple
    missing: tuple
    symbol: str
    source: str
    interval_ms: int
    as_of_ms: int
    raw_sha256: str
    timestamp_unit: str
    source_rows: int
    first_source_open_ms: int
    last_source_open_ms: int

    def to_report(self):
        return {'version':'ARIYAN-A011-HISTORY-INDEX-V1',
            'mode':'OFFLINE_QUALITY_INDEX_NO_GAP_REPAIR_OR_TRADING',
            'symbol':self.symbol,'source_label':self.source,
            'source_independently_authenticated':False,'live_authorized':False,
            'raw_sha256':self.raw_sha256,'hash_scope':'EXACT_WHOLE_SOURCE_CSV_BYTES',
            'input_format':'binance-spot','timestamp_unit':self.timestamp_unit,
            'interval_ms':self.interval_ms,'as_of_ms':self.as_of_ms,
            'first_source_open_ms':self.first_source_open_ms,'last_source_open_ms':self.last_source_open_ms,
            'source_rows':self.source_rows,'complete_rows':len(self.candles),
            'excluded_rows':len(self.exclusions),'missing_rows':sum(g.missing_rows for g in self.missing),
            'whole_source_accepted_for_contiguous_replay':len(self.candles)>=2 and len(self.spans)==1
                and not self.exclusions and not self.missing,
            'spans':[asdict(s) for s in self.spans],
            'exclusions':[asdict(e) for e in self.exclusions],
            'missing_intervals':[asdict(g) for g in self.missing],
            'policy':'EXCLUDE_DECLARED_BAD_ROWS_KEEP_NATIVE_TIMESTAMPS_SPLIT_EVERY_DISCONTINUITY',
            'limitations':[
                'Source labels and byte hashes do not independently authenticate market truth.',
                'Excluded rows and missing timestamps are not replaced, retimed, sorted or interpolated.',
                'This index cannot establish whether a gap reflects maintenance or another cause.',
                'Excluding incomplete windows can underrepresent outage/stress conditions.',
                'Training features and labels must stay within complete contiguous observation windows.',
                'Position/cash handling across unavailable prices is not implemented by this index.',
                'No strategy, predictability, source-quality certification or capital authority.']}

    def contiguous_dataset(self,span_index):
        integer(span_index,'span_index')
        if span_index>=len(self.spans):raise ValueError('Span index outside range')
        span=self.spans[span_index]
        if span.end_index_exclusive-span.start_index<2:
            raise ValueError('A singleton span is retained but cannot form a CandleDataset')
        return CandleDataset(self.candles[span.start_index:span.end_index_exclusive],
            self.symbol,self.interval_ms,self.source,self.as_of_ms,self.raw_sha256,'binance-spot',self.timestamp_unit)

    def complete_window(self,first_open_ms,end_exclusive_ms):
        """Check native elapsed-time coverage. Never join the two sides of a gap."""
        return complete_history_window((self,),first_open_ms,end_exclusive_ms)


def complete_history_window(indexes,first_open_ms,end_exclusive_ms):
    """Check elapsed-time coverage across ordered source files without imputation.

    Adjacent complete spans can continue across file boundaries. Any excluded
    or missing time prevents crossing it. Validate all source ordering before
    returning, even when the requested window is in the first file.
    """
    if type(indexes) not in (list,tuple) or not 1<=len(indexes)<=256:
        raise ValueError('Require 1..256 ordered HistoryIndex objects')
    integer(first_open_ms,'first_open_ms');integer(end_exclusive_ms,'end_exclusive_ms',1)
    previous=None;identity=None
    for index in indexes:
        if type(index) is not HistoryIndex:raise ValueError('A HistoryIndex is required')
        current=(index.symbol,index.interval_ms)
        if identity is None:identity=current
        if current!=identity:raise ValueError('Mixed symbols or intervals are not allowed')
        if previous is not None and index.first_source_open_ms<=previous:
            raise ValueError('Overlapping or unordered source files')
        previous=index.last_source_open_ms
    interval=identity[1]
    if first_open_ms>=end_exclusive_ms or first_open_ms%interval or end_exclusive_ms%interval:
        raise ValueError('Window must contain aligned positive elapsed time')
    cursor=first_open_ms
    for index in indexes:
        for span in index.spans:
            if span.last_close_ms<=cursor:continue
            if span.first_open_ms>cursor:return False
            cursor=span.last_close_ms
            if cursor>=end_exclusive_ms:return True
    return False


def _timestamp(text):
    if not re.fullmatch(r'[0-9]{1,18}',text):raise ValueError('Invalid integer timestamp')
    return int(text)


def inspect_history(path,*,symbol,source,interval_ms,as_of_ms,timestamp_unit='ms'):
    """Index headerless 12-column spot CSV; preserve complete bars and quarantine.

    Wrong field counts, unlocatable/misaligned/duplicate/unordered opens, future
    slots and byte/row limits reject the entire intake. On a valid open grid,
    incomplete close times or invalid OHLCV exclude that row with explicit reasons.
    Raw source bytes are hashed unchanged. No canonical full-series CSV is made.
    """
    integer(interval_ms,'interval_ms',1);integer(as_of_ms,'as_of_ms')
    if type(symbol) is not str or not re.fullmatch(r'[A-Z0-9][A-Z0-9_.:/-]{0,39}',symbol):
        raise ValueError('Invalid symbol label')
    if type(source) is not str or not source.strip() or len(source)>2048:
        raise ValueError('Nonempty bounded source label required')
    if timestamp_unit not in ('ms','us'):raise ValueError('Explicit ms or us timestamp unit required')
    with Path(path).open('rb') as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('CSV exceeds input byte limit')
    scale=1000 if timestamp_unit=='us' else 1
    reader=csv.reader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True)
    complete=[];excluded=[];missing=[];previous=None;first_source=None;count=0
    try:
        for row in reader:
            count+=1
            if count>MAX_ROWS:raise ValueError('CSV exceeds row limit')
            if len(row)!=12:raise ValueError('Expected twelve fields')
            fields=[field.strip() for field in row]
            opened=_timestamp(fields[0])
            if opened%scale:raise ValueError('Open timestamp is not an exact millisecond')
            opened_ms=opened//scale
            if opened_ms>253402300799000 or opened_ms%interval_ms:
                raise ValueError('Open timestamp outside supported aligned date range')
            if opened_ms+interval_ms>as_of_ms:raise ValueError('Incomplete/future source slot')
            if first_source is None:first_source=opened_ms
            if previous is not None:
                delta=opened_ms-previous
                if delta<=0:raise ValueError('Duplicate or unordered source open timestamp')
                if delta!=interval_ms:
                    missing.append(MissingInterval(previous+interval_ms,opened_ms,delta//interval_ms-1))
            previous=opened_ms
            reasons=[]
            expected=opened+interval_ms*scale-1
            try:
                closed=_timestamp(fields[6])
                if opened<=closed<expected:reasons.append('PARTIAL_INTERVAL')
                elif closed!=expected:reasons.append('INVALID_CLOSE_TIME')
            except ValueError:reasons.append('INVALID_CLOSE_TIME')
            candle=None
            try:
                values=[number(value,name,allow_zero=(name=='volume'))
                    for value,name in zip(fields[1:6],('open','high','low','close','volume'))]
                candle=Candle(opened_ms,*values)
            except (ValueError,TypeError,ArithmeticError):reasons.append('INVALID_OHLCV')
            if reasons:
                excluded.append(ExcludedRow(reader.line_num,opened_ms,tuple(reasons),fields[6],expected))
            else:complete.append(candle)
    except (ValueError,TypeError,csv.Error) as exc:
        raise ValueError(f'CSV line {reader.line_num}: {exc}') from exc
    if not count:raise ValueError('Empty history CSV')
    spans=[]
    for i,candle in enumerate(complete):
        if i==0 or candle.timestamp_ms-complete[i-1].timestamp_ms!=interval_ms:
            spans.append([i,i+1,candle.timestamp_ms,candle.timestamp_ms+interval_ms])
        else:
            spans[-1][1]=i+1;spans[-1][3]=candle.timestamp_ms+interval_ms
    return HistoryIndex(tuple(complete),tuple(CompleteSpan(*span) for span in spans),
        tuple(excluded),tuple(missing),symbol,source,interval_ms,as_of_ms,
        hashlib.sha256(raw).hexdigest(),timestamp_unit,count,first_source,previous)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv',required=True,type=Path)
    parser.add_argument('--symbol',required=True)
    parser.add_argument('--source',required=True)
    parser.add_argument('--interval-ms',required=True,type=int)
    parser.add_argument('--as-of-ms',required=True,type=int)
    parser.add_argument('--timestamp-unit',choices=('ms','us'),default='ms')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args(argv)
    try:
        index=inspect_history(args.csv,symbol=args.symbol,source=args.source,
            interval_ms=args.interval_ms,as_of_ms=args.as_of_ms,timestamp_unit=args.timestamp_unit)
        encoded=json.dumps(index.to_report(),sort_keys=True,indent=2,allow_nan=False)+'\n'
        with args.output.open('x',encoding='utf-8') as stream:stream.write(encoded)
    except (OSError,ValueError,TypeError,ArithmeticError,UnicodeError,csv.Error) as exc:
        parser.exit(2,'History index rejected: '+str(exc)+'\n')
    print('A011 QUALITY INDEX — NO REPAIR, REPLAY OR LIVE AUTHORITY')
    print('Complete/excluded/missing:',len(index.candles),len(index.exclusions),sum(g.missing_rows for g in index.missing))
    print('Complete contiguous spans:',len(index.spans))
    print('Report:',args.output)
    return 0

if __name__=='__main__':main()
