"""A024 verified development export to offline batch and HTML review; no live action."""
import argparse
import csv
import hashlib
import json
from decimal import Context, Decimal, localcontext
from pathlib import Path

from . import development_export as exports
from . import replay_batch as batch
from . import replay_view as view

REQUEST_VERSION = 'ARIYAN-A024-DEVELOPMENT-REVIEW-REQUEST-V1'
VERSION = 'ARIYAN-A024-DEVELOPMENT-REVIEW-V1'
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_BUNDLE_BYTES = 128 * 1024 * 1024
MAX_COMPLETE_BYTES = 256 * 1024
JOB_FIELDS = {'job_id', 'original_csv', 'plan', 'export_directory', 'instrument', 'schedule',
              'scenario', 'mapping_source', 'volume_unit', 'price_basis', 'config'}


def _sources():
    sources = exports._sources()
    folder = Path(__file__).parent
    for name in ('replay_batch.py', 'replay_view.py', 'development_review.py'):
        sources[name] = hashlib.sha256(batch.files._read_bytes(folder/name, batch.files.MAX_SOURCE_BYTES)).hexdigest()
    return sources


def _prepare(request_path):
    request, digest = batch.files._read_json(request_path, batch.MAX_MANIFEST_BYTES)
    raw = batch.files._read_bytes(request_path, batch.MAX_MANIFEST_BYTES)
    if hashlib.sha256(raw).hexdigest() != digest: raise ValueError('Request changed while reading')
    batch._object(request, {'version', 'experiment_note', 'jobs'}, 'review request')
    if request['version'] != REQUEST_VERSION: raise ValueError('Unsupported review request version')
    note = request['experiment_note']
    if type(note) is not str or not note.strip() or len(note) > 2048:
        raise ValueError('Explicit bounded experiment note required')
    jobs = request['jobs']
    if type(jobs) is not list or not 1 <= len(jobs) <= batch.MAX_JOBS:
        raise ValueError('Review requires 1..8 explicit jobs')
    sources = _sources(); total = len(raw)
    retained = [(request_path, batch.MAX_MANIFEST_BYTES, digest)]
    copied = {'REVIEW_REQUEST.json': raw}; prepared = []; bindings = []
    def read(path, maximum):
        nonlocal total
        remaining = MAX_INPUT_BYTES-total
        if remaining < 0: raise ValueError('Review input byte limit exceeded')
        content = batch.files._read_bytes(path, min(maximum, remaining))
        total += len(content)
        retained.append((path, maximum, hashlib.sha256(content).hexdigest()))
        return content
    for index, job in enumerate(jobs):
        batch._object(job, JOB_FIELDS, 'review job')
        if type(job['scenario']) is not str or job['scenario'] not in ('base', 'stress'):
            raise ValueError('Explicit base or stress scenario required')
        for name in ('original_csv', 'plan', 'export_directory', 'instrument', 'schedule'):
            if type(job[name]) is not str or not job[name] or len(job[name]) > 4096:
                raise ValueError('Bounded explicit input path required')
        paths = {name: batch._input(job[name], request_path.parent) for name in
                 ('original_csv', 'plan', 'instrument', 'schedule')}
        folder = Path(job['export_directory']).expanduser()
        if not folder.is_absolute(): folder = request_path.parent/folder
        folder = batch.files._path(folder)
        receipt = exports.verify_development_export(paths['original_csv'], paths['plan'], folder)
        original = read(paths['original_csv'], exports.MAX_BYTES)
        original_hash = hashlib.sha256(original).hexdigest()
        del original  # Original full input is never copied to the review directory.
        plan_raw = read(paths['plan'], exports.MAX_PLAN_BYTES)
        export_raw = {name: read(batch._input(folder/name), maximum) for name, maximum in
            (('development.csv', exports.MAX_BYTES), ('dataset-plan.json', exports.MAX_PLAN_BYTES),
             ('EXPORT.json', exports.MAX_RECEIPT_BYTES))}
        if (original_hash != receipt['original_dataset']['raw_sha256']
                or hashlib.sha256(plan_raw).hexdigest() != receipt['original_plan_bytes_sha256']
                or export_raw['dataset-plan.json'] != plan_raw
                or export_raw['EXPORT.json'] != exports._encoded(receipt)
                or hashlib.sha256(export_raw['development.csv']).hexdigest() != receipt['exported_dataset']['raw_sha256']):
            raise ValueError('Verified export/original changed while preparing review')
        instrument = read(paths['instrument'], batch.files.MAX_SPEC_BYTES)
        schedule = read(paths['schedule'], batch.files.MAX_SCHEDULE_BYTES)
        dataset = receipt['exported_dataset']
        prefix = f'inputs/job-{index:02d}'
        for name, content in export_raw.items(): copied[prefix+'/export/'+name] = content
        copied[prefix+'/instrument.json'] = instrument; copied[prefix+'/schedule.json'] = schedule
        candidate = {'job_id': job['job_id'], 'csv': prefix+'/export/development.csv',
            'instrument': prefix+'/instrument.json', 'schedule': prefix+'/schedule.json',
            'intake': {'symbol': dataset['symbol'], 'source': dataset['source_label'],
                'mapping_source': job['mapping_source'], 'volume_unit': job['volume_unit'],
                'price_basis': job['price_basis'], 'interval_ms': dataset['interval_ms'], 'anchor_ms': 0,
                'first_open_ms': dataset['first_open_ms'], 'end_exclusive_ms': dataset['last_close_ms'],
                'as_of_ms': dataset['as_of_ms']}, 'config': job['config']}
        # Enforce exact A021 types/schema before comparing numeric configurations.
        batch._request({'version': batch.REQUEST_VERSION, 'jobs': [candidate]})
        recorded = receipt['config'] if job['scenario'] == 'base' else receipt['stress_config']
        with localcontext(Context(prec=100)):
            for name, value in recorded.items():
                if name in ('short_window', 'long_window'):
                    equal = candidate['config'][name] == value
                else:
                    equal = Decimal(candidate['config'][name]) == Decimal(value)
                if not equal: raise ValueError('Configuration differs from selected A009 scenario: '+name)
        prepared.append(candidate)
        bindings.append({'job_id': job['job_id'], 'scenario': job['scenario'],
            'original_csv_sha256': original_hash, 'plan_bytes_sha256': receipt['original_plan_bytes_sha256'],
            'export_sha256': receipt['export_sha256'], 'development_csv_sha256': dataset['raw_sha256'],
            'development_range': receipt['development_range'], 'reserved_range': receipt['reserved_range'],
            'shared_parameter_policy': 'A009_SHARED_VALUES_MATCH_A017_EXTRA_SETTINGS_EXPLICIT',
            'a007_execution_equivalence_established': False, 'reserved_candles_supplied_to_replay': 0})
    manifest = {'version': batch.REQUEST_VERSION, 'jobs': prepared}
    batch._request(manifest)  # Also reject duplicate IDs across otherwise valid jobs.
    copied['batch-request.json'] = exports._encoded(manifest)
    evidence = {'version': VERSION, 'experiment_note': note, 'request_bytes_sha256': digest,
        'request_origin_directory_label': str(request_path.parent), 'jobs': bindings,
        'out_of_sample_status': 'NOT_ESTABLISHED', 'source_independently_authenticated': False,
        'reserved_performance_evaluated_by_this_operation': False, 'strategy_promoted': False,
        'global_reservation_access_control_established': False, 'live_authorized': False,
        'limitations': [
            'Every replay input is the complete verified development export; reserved original rows are parsed for integrity only.',
            'A009 shared parameters match, but A017 cash grids, rounding, sessions and drawdown exits change the execution model.',
            'Instrument/calendar/cost declarations remain caller supplied and unverified; this is not a venue adapter.',
            'Jobs are independent reset accounts; base and stress are correlated implementation comparisons, not strategy validation.',
            'The original plan, request, bindings and completion hashes are unsigned; prior nonaccess and publication time are unknown.',
            'Other APIs and the original full input remain directly accessible; this workflow is not global access control.',
            'No new model, parameter search, strategy promotion, shared portfolio or live authority.',
        ]}
    copied['PLAN_BINDINGS.json'] = exports._encoded(evidence)
    return copied, evidence, retained, sources


def _recheck(retained, sources):
    for path, maximum, digest in retained:
        if hashlib.sha256(batch.files._read_bytes(batch._input(path), maximum)).hexdigest() != digest:
            raise ValueError('Review input changed: '+path.name)
    if _sources() != sources: raise ValueError('Review implementation files changed')


def _check_copies(destination, copied):
    for relative, raw in copied.items():
        if batch.files._read_bytes(batch._input(destination/relative), len(raw)) != raw:
            raise ValueError('Review input copy changed: '+relative)


def run_development_review(request_path, destination):
    """Verify every export, then run A021 and render A022 in one new owned directory."""
    request_path = batch._input(request_path); destination = batch.files._path(destination)
    if destination.exists() or destination.is_symlink(): raise ValueError('Review destination already exists')
    if not destination.parent.is_dir(): raise ValueError('Review parent must already exist')
    copied, evidence, retained, sources = _prepare(request_path)
    _recheck(retained, sources)
    destination.mkdir()
    directories = [(destination, exports._identity(destination))]; written = []
    try:
        for relative, raw in copied.items():
            path = destination/relative
            parents = []; parent = path.parent
            while parent != destination:
                parents.append(parent); parent = parent.parent
            for parent in reversed(parents):
                if not parent.exists():
                    parent.mkdir(); directories.append((parent, exports._identity(parent)))
            with path.open('xb') as stream:
                written.append((path, exports._identity(path))); stream.write(raw)
        _check_copies(destination, copied)
        report = batch.run_batch(destination/'batch-request.json', destination/'BATCH.json')
        written.append((destination/'BATCH.json', exports._identity(destination/'BATCH.json')))
        html_raw = view.render_report(report)
        context = ('<section class="notice" role="note"><strong>Development-only workflow</strong>'
            '<p>Caller experiment note (unverified): '+view._e(evidence['experiment_note'])+'</p>'
            '<p>Replay inputs match verified development exports. Original full inputs were parsed for integrity. '
            'A009 shared settings match; cash/session/risk assumptions remain a different execution model. '
            'Out-of-sample status is not established.</p></section>').encode('utf-8')
        html_raw = html_raw.replace(b'<main>', b'<main>'+context, 1)
        if len(html_raw) > view.MAX_HTML_BYTES: raise ValueError('Contextual HTML exceeds byte bound')
        batch.files._write(destination/'REVIEW.html', html_raw)
        written.append((destination/'REVIEW.html', exports._identity(destination/'REVIEW.html')))
        _recheck(retained, sources)
        expected_artifacts = {**copied, 'BATCH.json': exports._encoded(report), 'REVIEW.html': html_raw}
        expected = {p.relative_to(destination).as_posix() for p,_ in written+directories[1:]}
        actual = {p.relative_to(destination).as_posix() for p in destination.rglob('*')}
        if actual != expected: raise ValueError('Unexpected files in owned review directory')
        hashes = {}; total = 0
        for path, identity in written:
            if not exports._still_owned(path, identity): raise ValueError('Review output path replaced')
            raw = batch.files._read_bytes(batch._input(path), MAX_BUNDLE_BYTES-total)
            if raw != expected_artifacts[path.relative_to(destination).as_posix()]:
                raise ValueError('Review artifact changed during workflow')
            total += len(raw)
            hashes[path.relative_to(destination).as_posix()] = hashlib.sha256(raw).hexdigest()
        complete = {'version': VERSION, 'mode': 'DEVELOPMENT_ONLY_OFFLINE_REVIEW_COMPLETE',
            'request_bytes_sha256': evidence['request_bytes_sha256'], 'source_file_sha256': sources,
            'batch_sha256': report['batch_sha256'], 'files_sha256': hashes,
            'summary_table': report['summary_table'], 'job_count': report['job_count'],
            'reserved_performance_evaluated_by_this_operation': False,
            'global_reservation_access_control_established': False, 'strategy_promoted': False,
            'live_authorized': False,
            'completion_policy': 'WRITTEN_LAST_NOT_ATOMIC_OR_AUTHENTICATED_NO_POWER_LOSS_GUARANTEE'}
        raw = exports._encoded(complete)
        if len(raw) > MAX_COMPLETE_BYTES or total+len(raw) > MAX_BUNDLE_BYTES:
            raise ValueError('Review bundle/completion byte limit exceeded')
        path = destination/'COMPLETE.json'
        with path.open('xb') as stream:
            written.append((path, exports._identity(path))); stream.write(raw)
        return complete
    except BaseException:
        # Remove only still-owned paths; do not adopt or erase unrelated writers' data.
        if not destination.is_symlink() and exports._still_owned(destination, directories[0][1]):
            for path, identity in reversed(written):
                if exports._still_owned(path, identity): path.unlink()
            for path, identity in reversed(directories):
                if exports._still_owned(path, identity):
                    try: path.rmdir()
                    except OSError: pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        complete = run_development_review(args.request, args.destination)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, UnicodeError, csv.Error, RecursionError) as exc:
        parser.exit(2, 'Development review rejected: '+str(exc)+'\n')
    print('A024 DEVELOPMENT REVIEW — INDEPENDENT ACCOUNTS; NO STRATEGY PROMOTION OR LIVE AUTHORITY')
    for row in complete['summary_table']:
        print(row['job_id'], row['cash_currency'], 'return%:', row['return_pct'],
              'fills:', row['filled_orders'], 'halted:', row['drawdown_halted'])
    print('Reserved performance evaluated by this operation: False')
    print('HTML:', args.destination/'REVIEW.html')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
