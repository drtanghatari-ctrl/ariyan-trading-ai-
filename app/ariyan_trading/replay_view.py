"""A022 static offline viewer for saved A021 batches; no replay or live actions."""
import argparse
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from decimal import Context, Decimal as D, ROUND_HALF_EVEN, localcontext
from pathlib import Path

from . import replay_batch as batch
from .instruments import ProductType, spec_from_record
from .session_replay import SessionReplayConfig

MAX_HTML_BYTES = 16 * 1024 * 1024
MAX_TEXT = 4096
CONTEXT = Context(prec=100, rounding=ROUND_HALF_EVEN)
SUMMARY_FIELDS = ('opening_cash', 'final_marked_equity', 'net_marked_pnl', 'return_pct',
    'total_fees', 'modeled_slippage_cost', 'filled_orders', 'max_observed_close_drawdown_pct',
    'drawdown_halted', 'final_units', 'last_mark_available_at_ms', 'last_mark_precedes_requested_end')


def _text(value):
    if type(value) is not str or len(value) > MAX_TEXT:
        raise ValueError('Bounded text required')
    return value


def _decimal(value):
    if (type(value) is not str or len(value) > 192
            or not re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', value)):
        raise ValueError('Finite fixed decimal string required')
    amount = D(value)
    if abs(amount) > D('1e26'):
        raise ValueError('Display numeric bound exceeded')
    return amount


def _integer(value, maximum=253402300799999):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('Bounded nonnegative integer required')
    return value


def _hash(value):
    if type(value) is not str or not re.fullmatch('[0-9a-f]{64}', value):
        raise ValueError('SHA-256 hex string required')


def _limitations(value):
    if type(value) is not list or not 1 <= len(value) <= 64:
        raise ValueError('Bounded nonempty limitations list required')
    for item in value:
        _text(item)


def _false(record, names):
    for name in names:
        if record.get(name) is not False:
            raise ValueError('Unsupported authority or provenance claim')


def validate_display_report(report):
    """Check unsigned hash and displayed-field consistency, not source authenticity.

    Does not rerun signals/fills, reopen inputs, or independently verify nested
    metadata, source hashes, venue rules, quote hashes or scientific validity.
    """
    expected = {'version', 'mode', 'account_policy', 'manifest_bytes_sha256', 'source_file_sha256',
        'python_version', 'snapshot_policy', 'jobs', 'summary_table', 'job_count',
        'portfolio_aggregation_performed', 'fx_conversion_performed', 'parameter_search_performed',
        'strategy_promoted', 'source_independently_authenticated', 'out_of_sample_status',
        'ledger_posted', 'live_authorized', 'limitations', 'batch_sha256'}
    batch._object(report, expected, 'A021 report')
    if (report['version'] != batch.VERSION or report['mode'] != 'OFFLINE_MULTI_INSTRUMENT_INDEPENDENT_ACCOUNTS'
            or report['account_policy'] != 'RESET_CASH_POSITIONS_SIGNALS_RISK_STATE_FOR_EVERY_JOB_NO_SHARED_CAPITAL'
            or report['out_of_sample_status'] != 'NOT_ESTABLISHED'
            or report['snapshot_policy'] != 'INDIVIDUAL_FILE_READS_RECHECKED_NOT_ATOMIC_OR_AUTHENTICATED'):
        raise ValueError('Unsupported batch contract')
    _false(report, ('portfolio_aggregation_performed', 'fx_conversion_performed', 'parameter_search_performed',
        'strategy_promoted', 'source_independently_authenticated', 'ledger_posted', 'live_authorized'))
    _hash(report['batch_sha256']); _hash(report['manifest_bytes_sha256'])
    body = {key: value for key, value in report.items() if key != 'batch_sha256'}
    if hashlib.sha256(batch.VERSION.encode()+b'\0'+batch.files._canonical(body)).hexdigest() != report['batch_sha256']:
        raise ValueError('Unsigned batch hash mismatch')
    _text(report['python_version']); _limitations(report['limitations'])
    sources = report['source_file_sha256']
    if type(sources) is not dict or not 1 <= len(sources) <= 32:
        raise ValueError('Bounded source hash map required')
    for name, digest in sources.items():
        _text(name); _hash(digest)
    jobs = report['jobs']; rows = report['summary_table']
    if (type(jobs) is not list or not 1 <= len(jobs) <= batch.MAX_JOBS
            or type(rows) is not list or len(rows) != len(jobs)
            or type(report['job_count']) is not int or report['job_count'] != len(jobs)):
        raise ValueError('Inconsistent batch job count')
    seen = set(); total_points = 0
    with localcontext(CONTEXT):
        for job, row in zip(jobs, rows):
            batch._object(job, {'job_id', 'instrument_identity', 'instrument_identity_sha256',
                'input_bytes_sha256', 'replay'}, 'saved job')
            label = job['job_id']
            if type(label) is not str or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', label) or label in seen:
                raise ValueError('Invalid/duplicate job ID')
            seen.add(label)
            batch._object(job['input_bytes_sha256'], {'csv', 'instrument', 'schedule'}, 'input hashes')
            for digest in job['input_bytes_sha256'].values(): _hash(digest)
            replay = job['replay']
            if type(replay) is not dict or replay.get('version') != 'ARIYAN-A017-SESSION-REPLAY-V1':
                raise ValueError('Supported saved replay required')
            if (replay.get('mode') != 'OFFLINE_TEST_REPLAY_NO_AUTHORITY'
                    or replay.get('strategy') != 'SMA_LEVEL_TEST_STRATEGY_NOT_VALIDATED'):
                raise ValueError('Unsupported replay contract')
            _false(replay, ('ledger_posted', 'strategy_promoted', 'production_risk_approval_established', 'live_authorized'))
            _limitations(replay['limitations'])
            config = replay['config']; batch._object(config, batch.CONFIG_FIELDS, 'saved config')
            for name, value in config.items():
                if type(value) is not (int if name in batch.INTEGER_CONFIG else str):
                    raise ValueError('Invalid saved config types')
            SessionReplayConfig(**config)
            intake = replay['intake']
            if type(intake) is not dict or intake.get('version') != 'ARIYAN-A015-SESSION-CANDLE-INTAKE-V1':
                raise ValueError('Supported saved intake required')
            _false(intake, ('source_independently_authenticated', 'instrument_mapping_independently_verified',
                'calendar_independently_verified', 'point_in_time_availability_established', 'live_authorized'))
            spec = spec_from_record(intake['instrument'])
            if (spec.product not in (ProductType.SPOT, ProductType.SHARE, ProductType.FUND_SHARE)
                    or config['cash_currency'] != spec.quote_currency
                    or config['cash_currency'] != spec.settlement_currency):
                raise ValueError('Unsupported saved cash product or currency')
            if (job['instrument_identity'] != spec.identity.to_record()
                    or job['instrument_identity_sha256'] != spec.identity.fingerprint()):
                raise ValueError('Instrument identity differs from saved terms')
            _text(intake['symbol_mapping']['dataset_symbol'])
            _text(intake['source']['label']); _limitations(intake['limitations'])
            grid = intake['session_assessment']['grid']
            start = _integer(grid['first_open_ms']); end = _integer(grid['end_exclusive_ms'])
            if end <= start: raise ValueError('Invalid saved time range')
            summary = replay['summary']; curve = replay['equity_curve']; trades = replay['trades']
            if (type(summary) is not dict or type(curve) is not list or not 1 <= len(curve) <= 10000
                    or type(trades) is not list or len(trades) > 1000
                    or _integer(intake['candles'], 10000) != len(curve)
                    or type(replay['decisions']) is not list or len(replay['decisions']) != len(curve)):
                raise ValueError('Invalid saved curve/trade counts')
            total_points += len(curve)
            if total_points > batch.MAX_TOTAL_GRID_SLOTS: raise ValueError('Total curve point limit exceeded')
            initial = _decimal(summary['opening_cash'])
            if initial != _decimal(config['opening_cash']) or not 0 < initial <= D('1e9'):
                raise ValueError('Opening cash differs from configuration')
            previous = start; peak = initial; max_dd = D(0); halt_time = None
            for point in curve:
                batch._object(point, {'close_timestamp_ms', 'cash', 'units', 'marked_equity',
                    'close_drawdown_pct', 'drawdown_halted'}, 'curve point')
                timestamp = _integer(point['close_timestamp_ms'])
                if not previous < timestamp <= end: raise ValueError('Curve times must strictly increase in range')
                previous = timestamp
                equity = _decimal(point['marked_equity'])
                if not 0 < equity <= D('1e9') or any(not 0 <= _decimal(point[n]) <= D('1e9') for n in ('cash', 'units')):
                    raise ValueError('Unsupported cash/unit/equity range')
                peak = max(peak, equity); drawdown = (peak-equity)/peak*100
                if _decimal(point['close_drawdown_pct']) != drawdown:
                    raise ValueError('Curve drawdown does not match observed equity')
                max_dd = max(max_dd, drawdown)
                if type(point['drawdown_halted']) is not bool: raise ValueError('Boolean halt state required')
                if point['drawdown_halted'] and halt_time is None: halt_time = timestamp
                if halt_time is not None and not point['drawdown_halted']: raise ValueError('Halt cannot unlatch')
            final = curve[-1]
            for name, field in (('final_cash', 'cash'), ('final_units', 'units'), ('final_marked_equity', 'marked_equity')):
                if _decimal(summary[name]) != _decimal(final[field]): raise ValueError('Terminal summary differs from curve')
            equity = _decimal(final['marked_equity'])
            if (_decimal(summary['net_marked_pnl']) != equity-initial
                    or _decimal(summary['return_pct']) != (equity/initial-1)*100
                    or _decimal(summary['max_observed_close_drawdown_pct']) != max_dd):
                raise ValueError('Summary arithmetic differs from saved equity curve')
            if (type(summary['drawdown_halted']) is not bool or summary['drawdown_halted'] != (halt_time is not None)
                    or summary['halt_available_at_ms'] is not None and type(summary['halt_available_at_ms']) is not int
                    or summary['halt_available_at_ms'] != halt_time
                    or type(summary['last_mark_precedes_requested_end']) is not bool
                    or summary['last_mark_precedes_requested_end'] != (previous < end)
                    or _integer(summary['last_mark_available_at_ms']) != previous
                    or _integer(summary['filled_orders'], 1000) != len(trades)):
                raise ValueError('Summary timing/count/halt state differs from saved curve')
            fees = D(0); slippage = D(0)
            for trade in trades:
                if type(trade) is not dict or trade.get('side') not in ('BUY', 'SELL'):
                    raise ValueError('Explicit simulated trade side required')
                _integer(trade['fill_timestamp_ms'])
                quote = trade['quote']
                for name in ('quantity', 'modeled_fill_price', 'posted_notional', 'fee', 'modeled_slippage_cost'):
                    if _decimal(quote[name]) < 0: raise ValueError('Negative trade amount')
                fees += _decimal(quote['fee']); slippage += _decimal(quote['modeled_slippage_cost'])
            if fees != _decimal(summary['total_fees']) or slippage != _decimal(summary['modeled_slippage_cost']):
                raise ValueError('Summary costs differ from saved quotes')
            expected_row = {'job_id': label, 'instrument_identity': job['instrument_identity'],
                'cash_currency': config['cash_currency'], **{name: summary[name] for name in SUMMARY_FIELDS}}
            if batch.files._canonical(row) != batch.files._canonical(expected_row):
                raise ValueError('Summary table differs from saved replay')
    return report


def _e(value):
    return html.escape(str(value), quote=True)


def _number(value):
    with localcontext(CONTEXT):
        return format(_decimal(value).quantize(D('0.000001')), ',f').rstrip('0').rstrip('.')


def _time(value):
    seconds, milliseconds = divmod(value, 1000)
    return datetime.fromtimestamp(seconds, timezone.utc).strftime('%Y-%m-%d %H:%M:%S')+f'.{milliseconds:03d} UTC'


def _chart(replay, index):
    curve = replay['equity_curve']; grid = replay['intake']['session_assessment']['grid']
    start, end = grid['first_open_ms'], grid['end_exclusive_ms']
    with localcontext(CONTEXT):
        initial = D(replay['summary']['opening_cash'])
        points = [(start, initial)] + [(p['close_timestamp_ms'], D(p['marked_equity'])) for p in curve]
        low, high = min(v for _, v in points), max(v for _, v in points)
        padding = max((high-low)*D('.08'), high*D('.001'), D('.000000000001'))
        bottom, top = low-padding, high+padding
        def xy(timestamp, value):
            return (D(32)+D(timestamp-start)/D(end-start)*576, D(174)-(value-bottom)/(top-bottom)*144)
        encoded = ' '.join(f'{x:.3f},{y:.3f}' for x,y in (xy(t,v) for t,v in points))
        _, baseline = xy(start, initial)
    return f'''<figure><svg viewBox="0 0 640 210" role="img" aria-labelledby="chart-{index}">
<title id="chart-{index}">Marked equity in {_e(replay['config']['cash_currency'])}; separate simulated account</title>
<line x1="32" x2="608" y1="{baseline:.3f}" y2="{baseline:.3f}" class="baseline"/>
<polyline points="{encoded}" class="equity"/><text x="32" y="18">{_e(_number(format(high,'f')))} high</text>
<text x="32" y="198">{_e(_number(format(low,'f')))} low</text></svg>
<figcaption>{_e(_time(start))} → {_e(_time(end))}<br>Opening cash and every observed close; elapsed-time axis.
Dashed line: opening cash. Joins between marks do not show intrabar prices or fills.</figcaption></figure>'''


STYLE = '''
:root{color-scheme:dark;--bg:#09121e;--panel:#122032;--line:#2a3b50;--muted:#b8c4d3;--gold:#dfba70;--red:#ff9c9c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:#edf2f8;font:16px/1.55 system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:28px 20px 60px}h1{font-size:clamp(1.8rem,5vw,3rem);line-height:1.15;margin:12px 0}
h2{margin:0;font-size:1.55rem;overflow-wrap:anywhere}h3{font-size:1rem;color:var(--gold)}p{margin:10px 0}.eyebrow{color:var(--gold);letter-spacing:.12em;font-size:.8rem;font-weight:700}
.muted,figcaption{color:var(--muted)}.notice{border-left:3px solid var(--gold);padding:12px 16px;background:#1b2735;margin:20px 0}
.scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:.88rem}th,td{text-align:right;padding:12px;border-bottom:1px solid var(--line);white-space:nowrap}th:first-child,td:first-child{text-align:left}
th{color:var(--muted);font-weight:500}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:24px;margin:24px 0;break-inside:avoid}
.identity{overflow-wrap:anywhere;color:var(--muted)}.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin:24px 0}
.stat span{display:block;font-size:.8rem;color:var(--muted)}.stat strong{font-size:1.35rem;overflow-wrap:anywhere}.negative{color:var(--red)}.positive{color:var(--gold)}
.badge{display:inline-block;border:1px solid var(--line);padding:4px 10px;margin:8px 8px 0 0;border-radius:20px;font-size:.8rem}.alert{color:var(--red);border-color:#8b5353}
figure{margin:20px 0}svg{width:100%;height:auto;background:#0b1624;border-radius:10px}svg text{fill:#b8c4d3;font:12px system-ui,sans-serif}.equity{fill:none;stroke:#dfba70;stroke-width:2;vector-effect:non-scaling-stroke}.baseline{stroke:#8497af;stroke-dasharray:5 5}
figcaption{font-size:.76rem}details{border-top:1px solid var(--line);padding:14px 0}summary{cursor:pointer;color:var(--gold)}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.78rem;background:#0b1624;padding:16px;border-radius:8px}li{margin:8px 0}
code{overflow-wrap:anywhere}footer{color:var(--muted);font-size:.8rem;overflow-wrap:anywhere;margin-top:32px}
@media(max-width:620px){main{padding:20px 12px 40px}.card{padding:18px 14px}.stats{grid-template-columns:repeat(2,minmax(0,1fr))}.stat strong{font-size:1.2rem}}
@media print{body{background:white;color:black}main{max-width:none}.card,.notice,svg,pre{background:white;color:black}details{display:block}summary{color:black}.muted,figcaption,footer,.identity{color:#444}}
'''


def render_report(report):
    validate_display_report(report)
    parts = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
        '<title>ARIYAN Trading AI — Offline replay review</title><style>'+STYLE+'</style></head><body><main>',
        '<header><div class="eyebrow">ARIYAN TRADING AI · OFFLINE REVIEW</div><h1>Markets, one clear view.</h1>',
        '<p class="muted">'+str(report['job_count'])+' replay jobs · separate simulated accounts · no live authority</p></header>',
        '<div class="notice"><strong>Historical simulation. Strategy not validated.</strong><br>',
        'Source data, calendars and instrument mappings remain unverified. Out-of-sample status is not established. ',
        'Accounts and returns are separate; do not add them as a portfolio.</div>',
        '<h2>Per-job results</h2><p class="muted">No ranking or combined balance. Costs are already reflected in results.</p>',
        '<div class="scroll"><table><thead><tr><th>Job / currency</th><th>Return</th><th>Close drawdown</th><th>Fees</th><th>Fills</th></tr></thead><tbody>']
    for row in report['summary_table']:
        parts.append('<tr><td>'+_e(row['job_id'])+' / '+_e(row['cash_currency'])+'</td><td>'+_e(_number(row['return_pct']))+
            '%</td><td>'+_e(_number(row['max_observed_close_drawdown_pct']))+'%</td><td>'+_e(_number(row['total_fees']))+
            '</td><td>'+str(row['filled_orders'])+'</td></tr>')
    parts.append('</tbody></table></div>')
    for index, job in enumerate(report['jobs']):
        replay = job['replay']; summary = replay['summary']; spec = replay['intake']['instrument']
        identity = job['instrument_identity']; currency = replay['config']['cash_currency']
        sign = 'negative' if D(summary['return_pct']) < 0 else 'positive'
        parts.append('<section class="card"><h2>'+_e(job['job_id'])+'</h2><p class="identity">'+
            _e(identity['venue'])+' / '+_e(identity['venue_instrument_id'])+' · '+_e(spec['display_symbol'])+
            ' · '+_e(spec['asset_class'])+' / '+_e(spec['product'])+'</p><p class="muted">Source (caller label): '+
            _e(replay['intake']['source']['label'])+'</p>')
        if summary['drawdown_halted']: parts.append('<span class="badge alert">HALTED IN SIMULATION</span>')
        if D(summary['final_units']) > 0: parts.append('<span class="badge">Terminal holdings remain marked</span>')
        if summary['last_mark_precedes_requested_end']: parts.append('<span class="badge alert">Last mark precedes requested end</span>')
        parts.append('<div class="stats">')
        for label, value, suffix in (('Return', summary['return_pct'], '%'),
                ('Max observed close drawdown', summary['max_observed_close_drawdown_pct'], '%'),
                ('Fees · '+currency, summary['total_fees'], ''), ('Simulated fills', str(summary['filled_orders']), '')):
            parts.append('<div class="stat"><span>'+_e(label)+'</span><strong class="'+(sign if label=='Return' else '')+'">'+
                _e(_number(value))+suffix+'</strong></div>')
        parts.append('</div><p>Opening cash <strong>'+_e(_number(summary['opening_cash']))+' '+_e(currency)+
            '</strong> → final marked equity <strong>'+_e(_number(summary['final_marked_equity']))+' '+_e(currency)+
            '</strong>.<br>Terminal units: '+_e(summary['final_units'])+' '+_e(spec['quantity_unit'])+
            '. Last mark: '+_e(_time(summary['last_mark_available_at_ms']))+'.</p>')
        parts.append(_chart(replay, index))
        parts.append('<p class="muted">Modeled slippage: '+_e(_number(summary['modeled_slippage_cost']))+' '+_e(currency)+
            ' (already reflected in fills). Terminal equity excludes forced liquidation and exit costs. ')
        parts.append('Close drawdown and simulated halts are not guaranteed loss limits.</p>')
        for title, value in (('Exact summary and configuration', {'summary': summary, 'config': replay['config']}),
                ('Recorded input fingerprints and source label', {'input_bytes_sha256': job['input_bytes_sha256'],
                    'instrument_identity_sha256': job['instrument_identity_sha256'],
                    'source_label': replay['intake']['source']['label']})):
            parts.append('<details><summary>'+title+'</summary><pre>'+_e(json.dumps(value, indent=2, sort_keys=True))+'</pre></details>')
        parts.append('<details><summary>Replay limitations</summary><ul>'+''.join('<li>'+_e(v)+'</li>' for v in
            replay['limitations']+replay['intake']['limitations'])+'</ul></details></section>')
    parts.append('<details><summary>Batch limitations</summary><ul>'+''.join('<li>'+_e(v)+'</li>' for v in report['limitations'])+'</ul></details>')
    parts.append('<footer><strong>File consistency checked; unsigned and unauthenticated.</strong><br>')
    parts.append('The saved hash, displayed arithmetic and repeated summary fields were checked. Signals and fills were not rerun; original inputs were not reopened. ')
    parts.append('A modified report can be rehashed. No scientific validation, market-data authenticity or capital authority is established.<br>')
    parts.append('Display rounds to six decimal places; exact summary values are available above. Charts retain every observed close and elapsed-time gaps.<br>')
    parts.append('Batch SHA-256: <code>'+_e(report['batch_sha256'])+'</code><br>Rendering: A022 · saved-report viewer only.</footer></main></body></html>')
    raw = ''.join(parts).encode('utf-8')
    if len(raw) > MAX_HTML_BYTES: raise ValueError('HTML report exceeds byte bound')
    return raw


def write_view(report_path, output):
    report_path = batch._input(report_path); output = batch.files._path(output)
    if output.exists() or output.is_symlink(): raise ValueError('Output already exists; never overwritten')
    if not output.parent.is_dir(): raise ValueError('Output parent must already exist')
    report, digest = batch.files._read_json(report_path, batch.MAX_REPORT_BYTES)
    raw = render_report(report)
    if hashlib.sha256(batch.files._read_bytes(batch._input(report_path), batch.MAX_REPORT_BYTES)).hexdigest() != digest:
        raise ValueError('Saved report changed while rendering')
    batch.files._write(output, raw)
    return report['job_count']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        count = write_view(args.report, args.output)
    except (OSError, ValueError, TypeError, KeyError, ArithmeticError, UnicodeError, RecursionError) as exc:
        parser.exit(2, 'Replay view rejected: '+str(exc)+'\n')
    print('A022 OFFLINE SAVED-REPORT VIEW — NO REPLAY OR LIVE AUTHORITY')
    print('Independent jobs:', count)
    print('HTML:', args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
