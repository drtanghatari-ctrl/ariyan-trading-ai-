"""A026 offline index of inspected saved reviews; separate accounts, no replay."""
import argparse
import hashlib
import json
from pathlib import Path

from . import review_inspector as inspector

batch = inspector.batch
view = inspector.view
exports = inspector.exports
VERSION = 'ARIYAN-A026-REVIEW-CATALOG-V1'
MAX_REVIEWS = 8
MAX_COPIED_HTML_BYTES = 32 * 1024 * 1024
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024


def _sources():
    result = inspector.workflow._sources()
    folder = Path(__file__).parent
    for name in ('review_inspector.py', 'review_catalog.py'):
        result[name] = hashlib.sha256(batch.files._read_bytes(folder/name, batch.files.MAX_SOURCE_BYTES)).hexdigest()
    return result


def _prepare(reviews, destination):
    if type(reviews) not in (tuple, list) or not 1 <= len(reviews) <= MAX_REVIEWS:
        raise ValueError('Catalog requires 1..8 explicit review directories')
    entries = []; copies = {}; retained = []; digests = set(); total = 0
    for index, value in enumerate(reviews):
        folder = batch.files._path(value)
        if not folder.is_dir(): raise ValueError('Existing review directory required')
        if destination.is_relative_to(folder): raise ValueError('Catalog cannot be created inside a source review')
        path = batch._input(folder/'COMPLETE.json')
        raw = batch.files._read_bytes(path, inspector.workflow.MAX_COMPLETE_BYTES)
        complete = inspector._json(raw)
        inspection = inspector.inspect_review(folder)
        if (inspection.get('version') != 'ARIYAN-A025-REVIEW-INSPECTION-V1'
                or inspection.get('status') != 'CONSISTENT_SAVED_ARTIFACTS_NOT_AUTHENTICATED'
                or any(inspection.get(name) is not True for name in
                    ('artifact_hashes_match','copied_intakes_match_saved_reports','html_matches_supported_renderer'))):
            raise ValueError('Supported successful inspection required')
        view._false(inspection, ('original_full_inputs_reopened','original_full_inputs_independently_verified',
            'replay_rerun','source_authenticity_established','live_authorized'))
        if batch.files._read_bytes(batch._input(path),inspector.workflow.MAX_COMPLETE_BYTES) != raw:
            raise ValueError('Completion record changed during inspection')
        inspector._same(complete['batch_sha256'],inspection['batch_sha256'])
        inspector._same(complete['job_count'],inspection['job_count'])
        digest = inspection['batch_sha256']
        if digest in digests: raise ValueError('Duplicate saved batch; copied reviews are not extra evidence')
        digests.add(digest)
        remaining = MAX_COPIED_HTML_BYTES-total
        if remaining < 0: raise ValueError('Copied review HTML limit exceeded')
        html_path = batch._input(folder/'REVIEW.html')
        page = batch.files._read_bytes(html_path,min(view.MAX_HTML_BYTES,remaining))
        total += len(page)
        page_hash = hashlib.sha256(page).hexdigest()
        if page_hash != complete['files_sha256']['REVIEW.html']:
            raise ValueError('HTML changed after review inspection')
        relative = f'reviews/review-{index:02d}.html'
        copies[relative] = page
        retained.extend(((path,inspector.workflow.MAX_COMPLETE_BYTES,hashlib.sha256(raw).hexdigest()),
                         (html_path,view.MAX_HTML_BYTES,page_hash)))
        entries.append({'review_index':index+1, 'source_directory_label':str(folder),
            'display_label':folder.name, 'html_file':relative, 'html_sha256':page_hash,
            'completion_bytes_sha256':hashlib.sha256(raw).hexdigest(), 'batch_sha256':digest,
            'job_count':inspection['job_count'], 'summary_table':complete['summary_table'],
            'inspection':inspection})
    return entries, copies, retained


def _render(entries):
    e = view._e
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        '<title>ARIYAN Trading AI — Saved review index</title><style>'+view.STYLE+
        'a{color:var(--gold);text-underline-offset:3px}</style></head><body><main>',
        '<header><div class="eyebrow">ARIYAN TRADING AI · OFFLINE REVIEW INDEX</div>',
        '<h1>Your saved market reviews.</h1><p class="muted">'+str(len(entries))+' reviewed folders · '+
        str(sum(entry['job_count'] for entry in entries))+' separate simulated accounts</p></header>',
        '<div class="notice"><strong>File consistency inspected; records remain unsigned.</strong><br>',
        'Historical test strategies remain unvalidated. Data and calendar authenticity and out-of-sample status ',
        'are not established. Returns and balances stay separate; there is no combined portfolio or strategy ranking.</div>',
        '<h2>Per-job snapshot</h2><p class="muted">Caller order preserved. Fees are already reflected in returns.</p>',
        '<div class="scroll"><table><thead><tr><th>Review / job</th><th>Instrument</th><th>Cash currency</th>',
        '<th>Return</th><th>Close drawdown</th><th>Fees</th><th>Fills</th><th>Halt</th></tr></thead><tbody>']
    for entry in entries:
        for row in entry['summary_table']:
            identity = row['instrument_identity']
            sign = 'negative' if view.D(row['return_pct']) < 0 else 'positive'
            parts.append('<tr><td><a href="'+entry['html_file']+'">'+str(entry['review_index'])+' / '+e(row['job_id'])+
                '</a></td><td>'+e(identity['venue'])+' / '+e(identity['venue_instrument_id'])+'</td><td>'+e(row['cash_currency'])+
                '</td><td class="'+sign+'">'+e(view._number(row['return_pct']))+'%</td><td>'+
                e(view._number(row['max_observed_close_drawdown_pct']))+'%</td><td>'+e(view._number(row['total_fees']))+
                '</td><td>'+str(row['filled_orders'])+'</td><td>'+('Latched' if row['drawdown_halted'] else 'Not latched')+'</td></tr>')
    parts.append('</tbody></table></div><h2>Open a detailed review</h2>')
    for entry in entries:
        currencies = list(dict.fromkeys(row['cash_currency'] for row in entry['summary_table']))
        parts.append('<section class="card"><h2>'+str(entry['review_index'])+' · '+e(entry['display_label'])+'</h2>'+
            '<p class="muted">'+str(entry['job_count'])+' independent jobs · currency labels: '+e(', '.join(currencies))+
            '</p><p><a href="'+entry['html_file']+'">Open saved charts, assumptions and exact values →</a></p>'+
            '<details><summary>Inspection and fingerprint</summary><p>Copied artifacts passed A025 consistency checks. '+
            'Original full inputs were not reopened; trades were not rerun. This is not source authentication.</p>'+
            '<pre>'+e(entry['batch_sha256'])+'</pre></details></section>')
    parts.append('<footer>Each linked page is a byte-for-byte copy of its inspected saved HTML. Jobs can share data, instruments '+
        'and periods, and are not independent validation evidence. Observed-close drawdown halts do not guarantee a maximum loss '+
        'or an exit fill. Display rounds to six decimal places; detailed pages retain exact summary values. '+
        'No new replay, portfolio aggregation, optimization, approval or live action occurred. '+
        'Keep this index and its reviews folder together when moving it. A026 saved snapshot, not ongoing monitoring.</footer></main></body></html>')
    raw = ''.join(parts).encode('utf-8')
    if len(raw)>MAX_INDEX_BYTES: raise ValueError('Catalog index exceeds byte bound')
    return raw


def _recheck(retained, sources):
    for path,maximum,digest in retained:
        if hashlib.sha256(batch.files._read_bytes(batch._input(path),maximum)).hexdigest()!=digest:
            raise ValueError('Saved review changed during catalog creation')
    if _sources()!=sources: raise ValueError('Catalog implementation files changed')


def build_catalog(reviews, destination):
    """Exclusively create a portable HTML index and copied pages; no data/engine run."""
    destination=batch.files._path(destination)
    if destination.exists() or destination.is_symlink(): raise ValueError('Catalog destination already exists')
    if not destination.parent.is_dir(): raise ValueError('Catalog parent must already exist')
    sources=_sources();entries,copies,retained=_prepare(reviews,destination)
    copies['index.html']=_render(entries)
    record={'version':VERSION,'mode':'OFFLINE_INSPECTED_SAVED_REVIEW_CATALOG',
        'reviews':entries,'review_count':len(entries),'job_count':sum(entry['job_count'] for entry in entries),
        'files_sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in copies.items()},
        'source_file_sha256':sources,'portfolio_aggregation_performed':False,'replay_rerun':False,
        'source_authenticity_established':False,'strategy_promoted':False,'live_authorized':False,
        'out_of_sample_status':'NOT_ESTABLISHED',
        'snapshot_policy':'CAPTURED_HTML_AND_COMPLETION_RECHECKED_NOT_ATOMIC_AUTHENTICATED_OR_CONTINUOUS',
        'limitations':['Original full datasets were not reopened and reserved performance was not newly evaluated.',
            'Inspection status describes the saved artifacts at inspection, not a continuing guarantee about source folders.',
            'Unsigned files/digests can be consistently recreated; no independent authenticity or capital authority.',
            'Different reviews may overlap; reject exact duplicate batches, but do not infer independence of other jobs.',
            'No shared balance, FX conversion, ranking, investment grade or validation approval.',
            'No atomic directory publication or power-loss durability; completion JSON alone is not authentication.']}
    record['catalog_sha256']=hashlib.sha256(VERSION.encode()+b'\0'+batch.files._canonical(record)).hexdigest()
    encoded=exports._encoded(record)
    if len(encoded)>MAX_METADATA_BYTES: raise ValueError('Catalog metadata exceeds byte bound')
    _recheck(retained,sources)
    destination.mkdir();directories=[(destination,exports._identity(destination))];written=[]
    try:
        folder=destination/'reviews';folder.mkdir();directories.append((folder,exports._identity(folder)))
        for name,raw in copies.items():
            path=destination/name
            with path.open('xb') as stream:
                written.append((path,exports._identity(path)));stream.write(raw)
        _recheck(retained,sources)
        for name,raw in copies.items():
            if batch.files._read_bytes(batch._input(destination/name),len(raw))!=raw:
                raise ValueError('Catalog output changed while writing')
        expected={p.relative_to(destination).as_posix() for p,_ in written+directories[1:]}
        if {p.relative_to(destination).as_posix() for p in destination.rglob('*')}!=expected:
            raise ValueError('Unexpected catalog directory contents')
        path=destination/'CATALOG.json'
        with path.open('xb') as stream:
            written.append((path,exports._identity(path)));stream.write(encoded)
        return record
    except BaseException:
        if not destination.is_symlink() and exports._still_owned(destination,directories[0][1]):
            for path,identity in reversed(written):
                if exports._still_owned(path,identity):path.unlink()
            for path,identity in reversed(directories):
                if exports._still_owned(path,identity):
                    try:path.rmdir()
                    except OSError:pass
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',required=True,nargs='+',type=Path)
    parser.add_argument('--destination',required=True,type=Path)
    args=parser.parse_args(argv)
    try:record=build_catalog(args.review,args.destination)
    except (OSError,ValueError,TypeError,KeyError,IndexError,ArithmeticError,UnicodeError,RecursionError) as exc:
        parser.exit(2,'Review catalog rejected: '+str(exc)+'\n')
    print('A026 OFFLINE SAVED REVIEW CATALOG — NO REPLAY OR LIVE AUTHORITY')
    print('Reviews:',record['review_count'],'Independent jobs:',record['job_count'])
    print('Index:',args.destination/'index.html')
    return 0


if __name__=='__main__':raise SystemExit(main())
