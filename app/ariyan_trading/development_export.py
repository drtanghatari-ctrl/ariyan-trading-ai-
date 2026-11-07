"""A023 verified-plan development CSV export; no performance evaluation or authority."""
import argparse
import csv
import hashlib
import io
import json
from decimal import Context, localcontext
from pathlib import Path

from .dataset_plan import MAX_PLAN_BYTES, verify_dataset_plan
from .market_data import HEADER, MAX_BYTES, load_candles
from . import session_replay_cli as files

VERSION = 'ARIYAN-A023-DEVELOPMENT-EXPORT-V1'
MAX_RECEIPT_BYTES = 256 * 1024
NAMES = ('development.csv', 'dataset-plan.json', 'EXPORT.json')


def _input(value):
    path = files._path(value)
    if not path.is_file():
        raise ValueError('Existing regular input file required: '+path.name)
    return path


def _sources():
    hashes = files._sources()
    folder = Path(__file__).parent
    for name in ('dataset_plan.py', 'replay.py', 'development_export.py'):
        hashes[name] = hashlib.sha256(files._read_bytes(folder/name, files.MAX_SOURCE_BYTES)).hexdigest()
    return hashes


def _encoded(record):
    return (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False)+'\n').encode('ascii')


def _csv_bytes(candles):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(HEADER)
    for candle in candles:
        values = []
        for name in HEADER[1:]:
            value = getattr(candle, name)
            text = format(value, 'f') if value != 0 else '0'
            values.append(text.rstrip('0').rstrip('.') if '.' in text else text)
        writer.writerow([candle.timestamp_ms, *values])
    raw = stream.getvalue().encode('ascii')
    if len(raw) > MAX_BYTES:
        raise ValueError('Normalized development CSV exceeds 32 MiB')
    return raw


def _prepare(csv_path, plan_path):
    csv_path, plan_path = _input(csv_path), _input(plan_path)
    if csv_path.samefile(plan_path):
        raise ValueError('CSV and plan must be separate inputs')
    sources = _sources()
    plan, plan_hash = files._read_json(plan_path, MAX_PLAN_BYTES)
    plan_raw = files._read_bytes(plan_path, MAX_PLAN_BYTES)
    if hashlib.sha256(plan_raw).hexdigest() != plan_hash:
        raise ValueError('Plan changed while reading')
    metadata = plan.get('dataset')
    if type(metadata) is not dict:
        raise ValueError('A009 dataset metadata required')
    dataset = load_candles(csv_path, symbol=metadata['symbol'], source=metadata['source_label'],
        interval_ms=metadata['interval_ms'], as_of_ms=metadata['as_of_ms'],
        input_format=metadata['input_format'], timestamp_unit=metadata['timestamp_unit'])
    with localcontext(Context(prec=100)):
        verified = verify_dataset_plan(dataset, plan)
    development, reserved = verified['ranges']
    selected = dataset.candles[development['start_index']:development['end_index_exclusive']]
    raw = _csv_bytes(selected)
    digest = hashlib.sha256(raw).hexdigest()
    receipt = {'version': VERSION, 'mode': 'DEVELOPMENT_EXPORT_ONLY_NO_EVALUATION',
        'original_dataset': verified['dataset'], 'original_plan_bytes_sha256': plan_hash,
        'development_range': development, 'reserved_range': reserved,
        'exported_dataset': {'filename': NAMES[0], 'symbol': dataset.symbol,
            'source_label': dataset.source, 'input_format': 'canonical', 'timestamp_unit': 'ms',
            'interval_ms': dataset.interval_ms, 'as_of_ms': dataset.as_of_ms,
            'candles': len(selected), 'first_open_ms': selected[0].timestamp_ms,
            'last_close_ms': selected[-1].timestamp_ms+dataset.interval_ms,
            'raw_sha256': digest, 'hash_scope': 'EXACT_EXPORTED_DEVELOPMENT_CSV_BYTES'},
        'config': verified['config'], 'stress_config': verified['stress_config'],
        'prior_data_access': verified['prior_data_access'],
        'out_of_sample_status': 'NOT_ESTABLISHED_CALLER_ASSERTION_ONLY',
        'selection_policy': 'EXACT_VERIFIED_A009_DEVELOPMENT_RANGE_ONLY_NO_RESERVED_ROWS',
        'csv_encoding_policy': 'CANONICAL_SIX_COLUMNS_MS_FIXED_DECIMAL_LF_NORMALIZED_SPELLINGS',
        'full_input_including_reserved_parsed_for_integrity': True,
        'reserved_candles_exported': 0, 'performance_evaluated_by_this_operation': False,
        'reserved_performance_evaluated_by_this_operation': False,
        'global_reservation_access_control_established': False,
        'authenticated_plan_publication_established': False,
        'source_independently_authenticated': False, 'live_authorized': False,
        'a017_configuration_derived': False, 'source_file_sha256': sources,
        'limitations': [
            'The full input, including reserved rows, is parsed for integrity; no performance is computed.',
            'Exported CSV bytes are normalized and have their own hash; the original full-input hash is separate.',
            'The unsigned plan and receipt do not authenticate publication time, source truth or prior nonaccess.',
            'Changing boundaries/settings and recreating a plan defines a different experiment; data cannot become unseen.',
            'This operation selects development rows only; other APIs and the original input remain directly accessible.',
            'A007/A009 configurations are preserved, not converted into A017 cash grids, drawdown limits or execution terms.',
            'A021 still requires explicit instrument/session files and complete cash-model configuration.',
            'No holdout-consumption ledger, strategy selection, optimization, profitability or trading approval.',
            'Source hashes record observed files, not loaded-code attestation; file rechecks are not an atomic snapshot.',
        ]}
    receipt['export_sha256'] = hashlib.sha256(VERSION.encode()+b'\0'+files._canonical(receipt)).hexdigest()
    encoded = _encoded(receipt)
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise ValueError('Export receipt exceeds byte bound')
    retained = ((csv_path, MAX_BYTES, dataset.raw_sha256), (plan_path, MAX_PLAN_BYTES, plan_hash))
    return {NAMES[0]: raw, NAMES[1]: plan_raw, NAMES[2]: encoded}, receipt, retained, sources


def _recheck(retained, sources):
    for path, maximum, expected in retained:
        if hashlib.sha256(files._read_bytes(_input(path), maximum)).hexdigest() != expected:
            raise ValueError('Input changed during export: '+path.name)
    if _sources() != sources:
        raise ValueError('Source files changed during export')


def _identity(path):
    stat = path.lstat()
    return stat.st_dev, stat.st_ino


def _still_owned(path, identity):
    try:
        return _identity(path) == identity
    except OSError:
        return False


def export_development(csv_path, plan_path, destination):
    """Create a new three-file directory, writing EXPORT.json last.

    Exclusive creation and owned-file cleanup do not establish atomic publication
    or power-loss durability. Verification requires the original full CSV/plan.
    """
    destination = files._path(destination)
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination already exists; nothing is replaced')
    if not destination.parent.is_dir():
        raise ValueError('Destination parent must already exist')
    expected, receipt, retained, sources = _prepare(csv_path, plan_path)
    _recheck(retained, sources)
    destination.mkdir()  # Exclusive directory creation; never adopt an existing directory.
    directory_identity = _identity(destination)
    written = []
    try:
        for name in NAMES:
            if name == NAMES[2]:
                _recheck(retained, sources)
            path = destination/name
            with path.open('xb') as stream:
                written.append((path, _identity(path)))
                stream.write(expected[name])
    except BaseException:
        # Preserve replacement paths or unrelated concurrent files during cleanup.
        if not destination.is_symlink() and _still_owned(destination, directory_identity):
            for path, identity in reversed(written):
                if _still_owned(path, identity):
                    path.unlink()
            try:
                destination.rmdir()
            except OSError:
                pass
        raise
    return receipt


def verify_development_export(csv_path, plan_path, destination):
    """Rebuild from the supplied original CSV/plan and compare all exported bytes."""
    destination = files._path(destination)
    if not destination.is_dir() or {p.name for p in destination.iterdir()} != set(NAMES):
        raise ValueError('Exact three-file export directory required')
    expected, receipt, retained, sources = _prepare(csv_path, plan_path)
    for name, maximum in ((NAMES[0], MAX_BYTES), (NAMES[1], MAX_PLAN_BYTES), (NAMES[2], MAX_RECEIPT_BYTES)):
        if files._read_bytes(_input(destination/name), maximum) != expected[name]:
            raise ValueError('Export differs from verified originals: '+name)
    _recheck(retained, sources)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('export', 'verify'))
    parser.add_argument('--csv', required=True, type=Path)
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        function = export_development if args.command == 'export' else verify_development_export
        receipt = function(args.csv, args.plan, args.destination)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, UnicodeError, csv.Error, RecursionError) as exc:
        parser.exit(2, 'Development export rejected: '+str(exc)+'\n')
    print('A023 DEVELOPMENT EXPORT — NO PERFORMANCE EVALUATION OR LIVE AUTHORITY')
    print('Development candles:', receipt['exported_dataset']['candles'])
    print('Reserved candles exported:', receipt['reserved_candles_exported'])
    print('Directory:', args.destination)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
