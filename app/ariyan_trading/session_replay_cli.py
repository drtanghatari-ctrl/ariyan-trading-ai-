"""A018 explicit-file offline session replay. No account, network or live action."""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from .cash_trade_math import PRICE_CONVENTION
from .instrument_data import PRICE_BASIS
from .instruments import spec_from_record
from .market_data import MAX_BYTES
from .session_data import load_session_candles
from .session_replay import SessionReplayConfig, run_session_replay
from .sessions import schedule_from_record

MAX_SPEC_BYTES = 65536
MAX_SCHEDULE_BYTES = 16*1024*1024
MAX_REPORT_BYTES = 32*1024*1024
MAX_SOURCE_BYTES = 256*1024
SOURCE_FILES = ('accounting.py','ledger_validation.py','market_data.py','instruments.py',
    'instrument_data.py','sessions.py','session_data.py','cash_trade_math.py',
    'session_replay.py','session_replay_cli.py')


def _path(value):
    path = Path(value).expanduser().absolute()
    if path.resolve() != path:
        raise ValueError('Symlink or non-normalized paths are not accepted')
    return path


def _read_bytes(path, maximum):
    path = _path(path)
    with path.open('rb') as stream:
        raw = stream.read(maximum+1)
    if len(raw)>maximum:
        raise ValueError('Input exceeds byte bound: '+path.name)
    return raw


def _unique(pairs):
    record = {}
    for key,value in pairs:
        if key in record:
            raise ValueError('Duplicate JSON key')
        record[key] = value
    return record


def _invalid(value):
    raise ValueError('Nonfinite JSON constant: '+value)


def _read_json(path, maximum):
    raw = _read_bytes(path,maximum)
    value = json.loads(raw.decode('utf-8'),object_pairs_hook=_unique,parse_constant=_invalid)
    if type(value) is not dict:
        raise ValueError('JSON object required: '+Path(path).name)
    return value,hashlib.sha256(raw).hexdigest()


def _sources():
    folder = _path(Path(__file__).parent)
    return {name:hashlib.sha256(_read_bytes(folder/name,MAX_SOURCE_BYTES)).hexdigest() for name in SOURCE_FILES}


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def _write(path, raw):
    stream = path.open('xb')
    try:
        with stream:
            stream.write(raw)
    except BaseException:
        path.unlink()
        raise


def _run(args):
    output = _path(args.output)
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; inputs and earlier reports are never overwritten')
    if not output.parent.is_dir():
        raise ValueError('Output parent directory must already exist')
    csv_path = _path(args.csv); spec_path = _path(args.instrument); schedule_path = _path(args.schedule)
    source_hashes = _sources()
    spec_record,spec_hash = _read_json(spec_path,MAX_SPEC_BYTES)
    schedule_record,schedule_hash = _read_json(schedule_path,MAX_SCHEDULE_BYTES)
    spec = spec_from_record(spec_record); schedule = schedule_from_record(schedule_record)
    config = SessionReplayConfig(opening_cash=args.opening_cash,cash_currency=args.cash_currency,
        cash_step=args.cash_step,fee_bps=args.fee_bps,slippage_bps=args.slippage_bps,
        price_convention=args.price_convention,max_buy_fraction=args.max_buy_fraction,
        max_position_fraction=args.max_position_fraction,max_close_drawdown_pct=args.max_close_drawdown_pct,
        short_window=args.short_window,long_window=args.long_window,max_trades=args.max_trades)
    series = load_session_candles(csv_path,symbol=args.symbol,source=args.source,spec=spec,schedule=schedule,
        interval_ms=args.interval_ms,anchor_ms=args.anchor_ms,first_open_ms=args.first_open_ms,
        end_exclusive_ms=args.end_exclusive_ms,as_of_ms=args.as_of_ms,price_basis=args.price_basis,
        volume_unit=args.volume_unit,mapping_source=args.mapping_source)
    replay = run_session_replay(series,config)
    report = {'version':'ARIYAN-A018-SESSION-REPLAY-RUN-V1','mode':'OFFLINE_EXPLICIT_INPUT_SESSION_REPLAY',
        'input_bytes_sha256':{'csv':series.raw_sha256,'instrument_json':spec_hash,'schedule_json':schedule_hash},
        'source_file_sha256':source_hashes,'python_version':sys.version,
        'snapshot_policy':'INDIVIDUAL_FILE_READS_RECHECKED_BEFORE_WRITE_NOT_AN_ATOMIC_OR_AUTHENTICATED_SNAPSHOT',
        'replay':replay,'source_independently_authenticated':False,'strategy_promoted':False,
        'live_authorized':False}
    report['run_sha256'] = hashlib.sha256(b'ARIYAN-A018-SESSION-REPLAY-RUN-V1\0'+_canonical(report)).hexdigest()
    raw = (json.dumps(report,indent=2,sort_keys=True,ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')
    if len(raw)>MAX_REPORT_BYTES:
        raise ValueError('Report exceeds 32 MiB')
    for path,maximum,expected in ((csv_path,MAX_BYTES,series.raw_sha256),
            (spec_path,MAX_SPEC_BYTES,spec_hash),(schedule_path,MAX_SCHEDULE_BYTES,schedule_hash)):
        if hashlib.sha256(_read_bytes(path,maximum)).hexdigest()!=expected:
            raise ValueError('Input changed during replay: '+path.name)
    if _sources()!=source_hashes:
        raise ValueError('Source files changed during replay')
    _write(output,raw)
    return report,output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('csv','instrument','schedule','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    for name in ('symbol','source','mapping-source','volume-unit','opening-cash','cash-currency',
                 'cash-step','fee-bps','slippage-bps'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--price-basis',required=True,choices=(PRICE_BASIS,))
    parser.add_argument('--price-convention',required=True,choices=(PRICE_CONVENTION,))
    for name in ('interval-ms','anchor-ms','first-open-ms','end-exclusive-ms','as-of-ms'):
        parser.add_argument('--'+name,required=True,type=int)
    parser.add_argument('--max-buy-fraction',default='0.10')
    parser.add_argument('--max-position-fraction',default='0.25')
    parser.add_argument('--max-close-drawdown-pct',default='10')
    parser.add_argument('--short-window',type=int,default=3)
    parser.add_argument('--long-window',type=int,default=5)
    parser.add_argument('--max-trades',type=int,default=1000)
    args = parser.parse_args(argv)
    try:
        report,output = _run(args)
    except (OSError,ValueError,TypeError,KeyError,ArithmeticError,UnicodeError,csv.Error,RecursionError) as exc:
        parser.exit(2,'Session replay rejected: '+str(exc)+'\n')
    print('A018 OFFLINE SESSION REPLAY — NO LIVE ACTIONS OR STRATEGY PROMOTION')
    print('Observed candles:',report['replay']['intake']['candles'])
    print('Simulated fills:',report['replay']['summary']['filled_orders'])
    print('Drawdown halted:',report['replay']['summary']['drawdown_halted'])
    print('Report:',output)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
