"""A021 bounded multi-instrument offline replay jobs; independent accounts only."""
import argparse
import csv
import hashlib
import json
import re
import sys
from dataclasses import fields
from pathlib import Path

from .instruments import spec_from_record
from .market_data import MAX_BYTES
from .session_data import load_session_candles
from .session_replay import SessionReplayConfig, run_session_replay
from .sessions import schedule_from_record
from . import session_replay_cli as files

REQUEST_VERSION = 'ARIYAN-A021-REPLAY-BATCH-REQUEST-V1'
VERSION = 'ARIYAN-A021-REPLAY-BATCH-V1'
MAX_JOBS = 8
MAX_MANIFEST_BYTES = 256 * 1024
MAX_TOTAL_INPUT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_GRID_SLOTS = 40000
MAX_REPORT_BYTES = 32 * 1024 * 1024
INTAKE_FIELDS = frozenset(('symbol', 'source', 'mapping_source', 'volume_unit', 'price_basis',
    'interval_ms', 'anchor_ms', 'first_open_ms', 'end_exclusive_ms', 'as_of_ms'))
CONFIG_FIELDS = frozenset(f.name for f in fields(SessionReplayConfig))
INTEGER_CONFIG = frozenset(('short_window', 'long_window', 'max_trades'))


def _object(value, keys, name):
    if type(value) is not dict or set(value) != keys:
        raise ValueError('Missing/unknown fields in ' + name)


def _input(value, parent=None):
    if not isinstance(value, (str, Path)):
        raise ValueError('Input path required')
    if isinstance(value, str) and (not value or len(value) > 4096):
        raise ValueError('Bounded nonempty input path required')
    path = Path(value).expanduser()
    if not path.is_absolute() and parent is not None:
        path = parent / path
    path = files._path(path)
    if not path.is_file():
        raise ValueError('Input must be an existing regular file: ' + path.name)
    return path


def _sources():
    hashes = files._sources()
    path = Path(__file__)
    hashes[path.name] = hashlib.sha256(files._read_bytes(path, files.MAX_SOURCE_BYTES)).hexdigest()
    return hashes


def _request(record):
    _object(record, {'version', 'jobs'}, 'batch request')
    if type(record['version']) is not str or record['version'] != REQUEST_VERSION:
        raise ValueError('Unsupported batch request version')
    jobs = record['jobs']
    if type(jobs) is not list or not 1 <= len(jobs) <= MAX_JOBS:
        raise ValueError('Batch requires 1..8 explicitly declared jobs')
    seen = set()
    for job in jobs:
        _object(job, {'job_id', 'csv', 'instrument', 'schedule', 'intake', 'config'}, 'job')
        label = job['job_id']
        if type(label) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', label):
            raise ValueError('Invalid job ID')
        if label in seen:
            raise ValueError('Duplicate job ID')
        seen.add(label)
        for name in ('csv', 'instrument', 'schedule'):
            if type(job[name]) is not str or not job[name] or len(job[name]) > 4096:
                raise ValueError('Explicit bounded file path required')
        _object(job['intake'], INTAKE_FIELDS, 'intake')
        for name in INTAKE_FIELDS:
            expected = int if name.endswith('_ms') else str
            if type(job['intake'][name]) is not expected:
                raise ValueError('Invalid intake field type: ' + name)
        _object(job['config'], CONFIG_FIELDS, 'config')
        for name in CONFIG_FIELDS:
            if type(job['config'][name]) is not (int if name in INTEGER_CONFIG else str):
                raise ValueError('Config numbers require decimal strings or exact window/limit integers')
        SessionReplayConfig(**job['config'])
    return jobs


def _prepare(manifest):
    record, manifest_hash = files._read_json(manifest, MAX_MANIFEST_BYTES)
    jobs = _request(record)
    retained = [(manifest, MAX_MANIFEST_BYTES, manifest_hash)]
    # Reserve the entire manifest allowance; do not trust a later file stat size.
    total_bytes = MAX_MANIFEST_BYTES
    if total_bytes > MAX_TOTAL_INPUT_BYTES:
        raise ValueError('Batch exceeds total input byte bound')
    total_slots = 0
    prepared = []
    for job in jobs:
        paths = {name: _input(job[name], manifest.parent) for name in ('csv', 'instrument', 'schedule')}
        hashes = {}
        records = {}
        for name, maximum in (('csv', MAX_BYTES), ('instrument', files.MAX_SPEC_BYTES),
                              ('schedule', files.MAX_SCHEDULE_BYTES)):
            raw = files._read_bytes(paths[name], min(maximum, MAX_TOTAL_INPUT_BYTES-total_bytes))
            total_bytes += len(raw)
            if total_bytes > MAX_TOTAL_INPUT_BYTES:
                raise ValueError('Batch exceeds total input byte bound')
            digest = hashlib.sha256(raw).hexdigest()
            hashes[name] = digest
            retained.append((paths[name], maximum, digest))
            if name != 'csv':
                # Use the same strict JSON reader as A018, and detect read changes.
                records[name], checked = files._read_json(paths[name], maximum)
                if checked != digest:
                    raise ValueError('Metadata changed while loading batch')
        spec = spec_from_record(records['instrument'])
        schedule = schedule_from_record(records['schedule'])
        series = load_session_candles(paths['csv'], spec=spec, schedule=schedule, **job['intake'])
        if series.raw_sha256 != hashes['csv']:
            raise ValueError('CSV changed while loading batch')
        assessment = series.to_report()['session_assessment']
        total_slots += sum(assessment['grid_slot_counts'].values())
        if total_slots > MAX_TOTAL_GRID_SLOTS:
            raise ValueError('Batch exceeds total grid-slot bound')
        prepared.append((job, series, SessionReplayConfig(**job['config']), hashes))
    return manifest_hash, retained, prepared


def run_batch(manifest, output):
    """Replay explicit jobs sequentially and exclusively create one complete report.

    Every account resets independently. There is no shared buying power, FX,
    portfolio return, optimization, model selection or authorization decision.
    """
    manifest = _input(manifest)
    output = files._path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Output already exists; no inputs or earlier reports are overwritten')
    if not output.parent.is_dir():
        raise ValueError('Output parent must already exist')
    source_hashes = _sources()
    manifest_hash, retained, prepared = _prepare(manifest)
    results = []
    for job, series, config, hashes in prepared:
        replay = run_session_replay(series, config)
        results.append({'job_id': job['job_id'], 'instrument_identity': series.spec.identity.to_record(),
            'instrument_identity_sha256': series.spec.identity.fingerprint(),
            'input_bytes_sha256': hashes, 'replay': replay})
    table = []
    for result in results:
        replay = result['replay']
        summary = replay['summary']
        table.append({'job_id': result['job_id'], 'instrument_identity': result['instrument_identity'],
            'cash_currency': replay['config']['cash_currency'],
            **{name: summary[name] for name in ('opening_cash', 'final_marked_equity', 'net_marked_pnl',
                'return_pct', 'total_fees', 'modeled_slippage_cost', 'filled_orders',
                'max_observed_close_drawdown_pct', 'drawdown_halted', 'final_units',
                'last_mark_available_at_ms', 'last_mark_precedes_requested_end')}})
    report = {'version': VERSION, 'mode': 'OFFLINE_MULTI_INSTRUMENT_INDEPENDENT_ACCOUNTS',
        'account_policy': 'RESET_CASH_POSITIONS_SIGNALS_RISK_STATE_FOR_EVERY_JOB_NO_SHARED_CAPITAL',
        'manifest_bytes_sha256': manifest_hash, 'source_file_sha256': source_hashes,
        'python_version': sys.version,
        'snapshot_policy': 'INDIVIDUAL_FILE_READS_RECHECKED_NOT_ATOMIC_OR_AUTHENTICATED',
        'jobs': results, 'summary_table': table, 'job_count': len(results),
        'portfolio_aggregation_performed': False, 'fx_conversion_performed': False,
        'parameter_search_performed': False, 'strategy_promoted': False,
        'source_independently_authenticated': False, 'out_of_sample_status': 'NOT_ESTABLISHED',
        'ledger_posted': False, 'live_authorized': False,
        'limitations': [
            'Independent reset accounts: cash, PnL and returns must not be combined as one portfolio.',
            'Currencies remain per job; matching currency labels do not imply shared or additive capital.',
            'Jobs may share data, instruments and periods; they are not independent validation evidence.',
            'Only existing unlevered cash spot/share/fund-share replay mechanics are available.',
            'Declared metal/energy spot terms do not establish a tradable product or venue adapter.',
            'No futures, CFDs, shorting, margin, FX, corporate actions, dividends or roll accounting.',
            'Caller input selection and prior data access are unknown; reserved ranges are not enforced here.',
            'All nested A017 session, fillability, drawdown, terminal-mark and provenance limitations remain.',
            'No optimization occurs here; caller-selected variants can still cause selection bias.',
            'Source hashes identify observed files, not loaded-code attestation or authenticated provenance.',
        ]}
    report['batch_sha256'] = hashlib.sha256(VERSION.encode('ascii')+b'\0'+files._canonical(report)).hexdigest()
    raw = (json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)+'\n').encode('ascii')
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('Batch report exceeds byte bound')
    for path, maximum, expected in retained:
        if hashlib.sha256(files._read_bytes(_input(path), maximum)).hexdigest() != expected:
            raise ValueError('Input changed during batch: '+path.name)
    if _sources() != source_hashes:
        raise ValueError('Source files changed during batch')
    files._write(output, raw)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_batch(args.manifest, args.output)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, UnicodeError, csv.Error, RecursionError) as exc:
        parser.exit(2, 'Replay batch rejected: '+str(exc)+'\n')
    print('A021 OFFLINE REPLAY BATCH — INDEPENDENT ACCOUNTS; NO LIVE AUTHORITY')
    for row in report['summary_table']:
        identity = row['instrument_identity']
        print(row['job_id'], identity['venue']+'/'+identity['venue_instrument_id'],
              'cash:', row['cash_currency'], 'return%:', row['return_pct'],
              'fills:', row['filled_orders'], 'halted:', row['drawdown_halted'])
    print('Report:', args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
