"""A025 read-only saved A024 review consistency inspection; not authentication."""
import argparse
import hashlib
import json
from decimal import Context, Decimal, localcontext
from pathlib import Path

from . import development_review as workflow

batch = workflow.batch
view = workflow.view
exports = workflow.exports
ROOT_FILES = {'REVIEW_REQUEST.json', 'PLAN_BINDINGS.json', 'batch-request.json',
              'BATCH.json', 'REVIEW.html', 'COMPLETE.json'}
MAX_NODES = 128


def _json(raw):
    record = json.loads(raw.decode('utf-8'), object_pairs_hook=batch.files._unique,
                        parse_constant=batch.files._invalid)
    if type(record) is not dict: raise ValueError('JSON object required')
    return record


def _same(actual, expected):
    if batch.files._canonical(actual) != batch.files._canonical(expected):
        raise ValueError('Saved records disagree')


def inspect_review(directory):
    """Inspect only copied artifacts. All digests/claims remain unsigned."""
    directory = batch.files._path(directory)
    if not directory.is_dir(): raise ValueError('Existing review directory required')
    raw_complete = batch.files._read_bytes(batch._input(directory/'COMPLETE.json'), workflow.MAX_COMPLETE_BYTES)
    complete = _json(raw_complete)
    batch._object(complete, {'version', 'mode', 'request_bytes_sha256', 'source_file_sha256',
        'batch_sha256', 'files_sha256', 'summary_table', 'job_count',
        'reserved_performance_evaluated_by_this_operation', 'global_reservation_access_control_established',
        'strategy_promoted', 'live_authorized', 'completion_policy'}, 'completion record')
    count = complete['job_count']
    if type(count) is not int or not 1 <= count <= batch.MAX_JOBS:
        raise ValueError('Invalid completion job count')
    if (complete['version'] != workflow.VERSION or complete['mode'] != 'DEVELOPMENT_ONLY_OFFLINE_REVIEW_COMPLETE'
            or complete['completion_policy'] != 'WRITTEN_LAST_NOT_ATOMIC_OR_AUTHENTICATED_NO_POWER_LOSS_GUARANTEE'):
        raise ValueError('Unsupported completion contract')
    view._false(complete, ('reserved_performance_evaluated_by_this_operation',
        'global_reservation_access_control_established', 'strategy_promoted', 'live_authorized'))
    expected_files = set(ROOT_FILES); expected_dirs = {'inputs'}
    limits = {'REVIEW_REQUEST.json':batch.MAX_MANIFEST_BYTES, 'PLAN_BINDINGS.json':workflow.MAX_COMPLETE_BYTES,
        'batch-request.json':batch.MAX_MANIFEST_BYTES, 'BATCH.json':batch.MAX_REPORT_BYTES,
        'REVIEW.html':view.MAX_HTML_BYTES, 'COMPLETE.json':workflow.MAX_COMPLETE_BYTES}
    for index in range(count):
        prefix = f'inputs/job-{index:02d}'
        expected_dirs.update((prefix, prefix+'/export'))
        for suffix, maximum in (('export/development.csv', exports.MAX_BYTES),
                ('export/dataset-plan.json', exports.MAX_PLAN_BYTES), ('export/EXPORT.json', exports.MAX_RECEIPT_BYTES),
                ('instrument.json', batch.files.MAX_SPEC_BYTES), ('schedule.json', batch.files.MAX_SCHEDULE_BYTES)):
            name = prefix+'/'+suffix; expected_files.add(name); limits[name] = maximum
    seen = set()
    for path in directory.rglob('*'):
        if len(seen) >= MAX_NODES: raise ValueError('Review tree exceeds node limit')
        if path.is_symlink() or batch.files._path(path) != path: raise ValueError('Symlink artifact rejected')
        name = path.relative_to(directory).as_posix(); seen.add(name)
        if name in expected_dirs:
            if not path.is_dir(): raise ValueError('Directory shape mismatch')
        elif name in expected_files:
            if not path.is_file(): raise ValueError('Regular artifact required')
        else: raise ValueError('Unknown review artifact')
    if seen != expected_files | expected_dirs: raise ValueError('Missing review artifacts')
    hashes = complete['files_sha256']
    batch._object(hashes, expected_files-{'COMPLETE.json'}, 'artifact hash map')
    raw = {'COMPLETE.json':raw_complete}; total = len(raw_complete)
    for name in sorted(expected_files-{'COMPLETE.json'}):
        view._hash(hashes[name])
        remaining = workflow.MAX_BUNDLE_BYTES-total
        if remaining < 0: raise ValueError('Review byte limit exceeded')
        content = batch.files._read_bytes(batch._input(directory/name), min(limits[name],remaining))
        total += len(content); raw[name] = content
        if hashlib.sha256(content).hexdigest() != hashes[name]: raise ValueError('Artifact hash mismatch: '+name)
    request = _json(raw['REVIEW_REQUEST.json']); manifest = _json(raw['batch-request.json'])
    evidence = _json(raw['PLAN_BINDINGS.json']); report = _json(raw['BATCH.json'])
    batch._object(request, {'version','experiment_note','jobs'}, 'copied request')
    if request['version'] != workflow.REQUEST_VERSION: raise ValueError('Unsupported copied request')
    if type(request['experiment_note']) is not str or not request['experiment_note'].strip() or len(request['experiment_note'])>2048:
        raise ValueError('Experiment note required')
    if type(request['jobs']) is not list or len(request['jobs']) != count: raise ValueError('Request count mismatch')
    if hashlib.sha256(raw['REVIEW_REQUEST.json']).hexdigest() != complete['request_bytes_sha256']:
        raise ValueError('Copied request hash mismatch')
    if evidence.get('version') != workflow.VERSION or evidence.get('experiment_note') != request['experiment_note']:
        raise ValueError('Plan binding context mismatch')
    view._false(evidence, ('source_independently_authenticated', 'reserved_performance_evaluated_by_this_operation',
        'strategy_promoted', 'global_reservation_access_control_established', 'live_authorized'))
    if evidence.get('out_of_sample_status') != 'NOT_ESTABLISHED': raise ValueError('Unsupported validation claim')
    _same(evidence['request_bytes_sha256'], complete['request_bytes_sha256'])
    if type(evidence['jobs']) is not list or len(evidence['jobs']) != count: raise ValueError('Binding count mismatch')
    jobs = batch._request(manifest)
    if len(jobs) != count: raise ValueError('Manifest count mismatch')
    with localcontext(Context(prec=100)):
        for index, (job, declared, binding) in enumerate(zip(jobs,request['jobs'],evidence['jobs'])):
            batch._object(declared, workflow.JOB_FIELDS, 'copied request job')
            for name in ('original_csv','plan','export_directory','instrument','schedule'):
                if type(declared[name]) is not str or not declared[name] or len(declared[name])>4096:
                    raise ValueError('Invalid recorded original path')
            if declared['scenario'] not in ('base','stress'): raise ValueError('Unsupported scenario')
            prefix = f'inputs/job-{index:02d}'
            # Do not follow arbitrary file references from an unsigned manifest.
            for field, suffix in (('csv','export/development.csv'),('instrument','instrument.json'),('schedule','schedule.json')):
                _same(job[field], prefix+'/'+suffix)
            plan_raw = raw[prefix+'/export/dataset-plan.json']; plan = _json(plan_raw)
            receipt = _json(raw[prefix+'/export/EXPORT.json'])
            if (plan.get('version')!='ARIYAN-A009-DATASET-PLAN-V1'
                    or plan.get('mode')!='OFFLINE_RESERVATION_NO_EVALUATION'
                    or plan.get('reservation_enforced_by_runtime') is not False
                    or plan.get('live_authorized') is not False
                    or receipt.get('version') != exports.VERSION
                    or receipt.get('mode')!='DEVELOPMENT_EXPORT_ONLY_NO_EVALUATION'):
                raise ValueError('Unsupported copied plan/export contract')
            view._hash(receipt['original_dataset']['raw_sha256'])
            body = {k:v for k,v in receipt.items() if k!='export_sha256'}
            if hashlib.sha256(exports.VERSION.encode()+b'\0'+batch.files._canonical(body)).hexdigest()!=receipt.get('export_sha256'):
                raise ValueError('Unsigned export digest mismatch')
            view._false(receipt, ('performance_evaluated_by_this_operation','reserved_performance_evaluated_by_this_operation',
                'global_reservation_access_control_established','authenticated_plan_publication_established',
                'source_independently_authenticated','live_authorized','a017_configuration_derived'))
            _same(receipt['reserved_candles_exported'],0)
            _same(receipt['original_plan_bytes_sha256'], hashlib.sha256(plan_raw).hexdigest())
            for receipt_key, plan_key in (('original_dataset','dataset'),('config','config'),('stress_config','stress_config'),
                                          ('prior_data_access','prior_data_access')):
                _same(receipt[receipt_key], plan[plan_key])
            _same(receipt['development_range'],plan['ranges'][0]); _same(receipt['reserved_range'],plan['ranges'][1])
            dataset = receipt['exported_dataset']
            _same(dataset['raw_sha256'],hashlib.sha256(raw[prefix+'/export/development.csv']).hexdigest())
            intake = {'symbol':dataset['symbol'],'source':dataset['source_label'],'mapping_source':declared['mapping_source'],
                'volume_unit':declared['volume_unit'],'price_basis':declared['price_basis'],'interval_ms':dataset['interval_ms'],
                'anchor_ms':0,'first_open_ms':dataset['first_open_ms'],'end_exclusive_ms':dataset['last_close_ms'],
                'as_of_ms':dataset['as_of_ms']}
            _same(job['intake'],intake); _same(job['job_id'],declared['job_id']); _same(job['config'],declared['config'])
            selected = receipt['config' if declared['scenario']=='base' else 'stress_config']
            for name,value in selected.items():
                if name in ('short_window','long_window'): _same(job['config'][name],value)
                elif Decimal(job['config'][name]) != Decimal(value): raise ValueError('Shared scenario setting mismatch')
            expected_binding = {'job_id':job['job_id'],'scenario':declared['scenario'],
                'original_csv_sha256':receipt['original_dataset']['raw_sha256'],
                'plan_bytes_sha256':receipt['original_plan_bytes_sha256'],'export_sha256':receipt['export_sha256'],
                'development_csv_sha256':dataset['raw_sha256'],'development_range':receipt['development_range'],
                'reserved_range':receipt['reserved_range'],
                'shared_parameter_policy':'A009_SHARED_VALUES_MATCH_A017_EXTRA_SETTINGS_EXPLICIT',
                'a007_execution_equivalence_established':False,'reserved_candles_supplied_to_replay':0}
            _same(binding,expected_binding)
    view.validate_display_report(report)
    _same(report['job_count'],count)
    _same(report['batch_sha256'],complete['batch_sha256']); _same(report['summary_table'],complete['summary_table'])
    _same(report['manifest_bytes_sha256'],hashlib.sha256(raw['batch-request.json']).hexdigest())
    if type(complete['source_file_sha256']) is not dict or not 1<=len(complete['source_file_sha256'])<=32:
        raise ValueError('Bounded producer source hash map required')
    for name,digest in complete['source_file_sha256'].items(): view._text(name); view._hash(digest)
    for name,digest in report['source_file_sha256'].items(): _same(complete['source_file_sha256'].get(name),digest)
    # Use the already checked request and fixed paths, rather than rereading a
    # mutable manifest whose references might have changed since path validation.
    intake_bytes=batch.MAX_MANIFEST_BYTES; grid_slots=0
    for index,job in enumerate(jobs):
        prefix=f'inputs/job-{index:02d}'
        intake_bytes+=sum(len(raw[prefix+'/'+suffix]) for suffix in
            ('export/development.csv','instrument.json','schedule.json'))
        if intake_bytes>batch.MAX_TOTAL_INPUT_BYTES: raise ValueError('Copied batch input bound exceeded')
        series=batch.load_session_candles(batch._input(directory/prefix/'export/development.csv'),
            spec=batch.spec_from_record(_json(raw[prefix+'/instrument.json'])),
            schedule=batch.schedule_from_record(_json(raw[prefix+'/schedule.json'])), **job['intake'])
        input_hashes={name:hashlib.sha256(raw[prefix+'/'+suffix]).hexdigest() for name,suffix in
            (('csv','export/development.csv'),('instrument','instrument.json'),('schedule','schedule.json'))}
        _same(series.raw_sha256,input_hashes['csv'])
        intake=series.to_report()
        slots=sum(intake['session_assessment']['grid_slot_counts'].values());grid_slots+=slots
        if slots>10000 or grid_slots>batch.MAX_TOTAL_GRID_SLOTS: raise ValueError('Copied replay grid bound exceeded')
        saved = report['jobs'][index]
        _same(saved['job_id'],jobs[index]['job_id']); _same(saved['input_bytes_sha256'],input_hashes)
        _same(saved['replay']['intake'],intake)
        receipt = _json(raw[f'inputs/job-{index:02d}/export/EXPORT.json'])
        development = receipt['development_range']; reserved = receipt['reserved_range']
        _same(development['role'],'DEVELOPMENT'); _same(reserved['role'],'RESERVED')
        _same(development['start_index'],0); _same(development['candles'],len(series.candles))
        _same(development['end_index_exclusive'],len(series.candles))
        _same(reserved['start_index'],len(series.candles))
        _same(reserved['first_open_ms'],series.end_exclusive_ms)
        _same(receipt['exported_dataset']['candles'],len(series.candles))
        if exports._csv_bytes(series.candles)!=raw[f'inputs/job-{index:02d}/export/development.csv']:
            raise ValueError('Export CSV is not in its declared normalized form')
    html_raw = view.render_report(report)
    context = ('<section class="notice" role="note"><strong>Development-only workflow</strong>'
        '<p>Caller experiment note (unverified): '+view._e(evidence['experiment_note'])+'</p>'
        '<p>Replay inputs match verified development exports. Original full inputs were parsed for integrity. '
        'A009 shared settings match; cash/session/risk assumptions remain a different execution model. '
        'Out-of-sample status is not established.</p></section>').encode('utf-8')
    if html_raw.replace(b'<main>',b'<main>'+context,1)!=raw['REVIEW.html']:
        raise ValueError('HTML differs from the supported saved-report renderer')
    for name,content in raw.items():
        if batch.files._read_bytes(batch._input(directory/name),limits[name])!=content:
            raise ValueError('Artifact changed during inspection')
    final_seen=set()
    for path in directory.rglob('*'):
        if len(final_seen)>=MAX_NODES or path.is_symlink(): raise ValueError('Review tree changed during inspection')
        final_seen.add(path.relative_to(directory).as_posix())
    if final_seen!=seen: raise ValueError('Review tree changed during inspection')
    return {'version':'ARIYAN-A025-REVIEW-INSPECTION-V1','status':'CONSISTENT_SAVED_ARTIFACTS_NOT_AUTHENTICATED',
        'job_count':count,'batch_sha256':report['batch_sha256'],'artifact_hashes_match':True,
        'copied_intakes_match_saved_reports':True,'html_matches_supported_renderer':True,
        'original_full_inputs_reopened':False,'original_full_inputs_independently_verified':False,
        'replay_rerun':False,'source_authenticity_established':False,'live_authorized':False,
        'limitations':['All artifacts/digests remain unsigned and can be edited and consistently recreated.',
            'Original full CSVs, reserved candle values, plan publication time and prior nonaccess are not verified.',
            'This is copied-artifact consistency, not independent validation of signals, fills or trading authority.',
            'Current renderer semantics must match; rechecks are not an atomic or authenticated snapshot.']}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',required=True,type=Path)
    args=parser.parse_args(argv)
    try: result=inspect_review(args.review)
    except (OSError,ValueError,TypeError,KeyError,IndexError,ArithmeticError,UnicodeError,RecursionError) as exc:
        parser.exit(2,'Review inspection rejected: '+str(exc)+'\n')
    print(json.dumps(result,indent=2,sort_keys=True,allow_nan=False))
    return 0


if __name__=='__main__': raise SystemExit(main())
