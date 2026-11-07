"""A010 public Binance spot archive intake. No credentials, replay or orders."""

import argparse
import csv
import hashlib
import io
import json
import re
import shutil
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .market_data import HEADER, MAX_BYTES, MAX_ROWS, integer, load_candles

ORIGIN = 'https://data.binance.vision/data/spot/monthly/klines'
DOCUMENTATION = 'https://github.com/binance/binance-public-data'
INTERVALS = {'1m': 60000, '3m': 180000, '5m': 300000, '15m': 900000,
             '30m': 1800000, '1h': 3600000, '2h': 7200000, '4h': 14400000,
             '6h': 21600000, '8h': 28800000, '12h': 43200000, '1d': 86400000}
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024


def _month(value):
    if type(value) is not str or not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])', value):
        raise ValueError('Month must be YYYY-MM')
    year, month = map(int, value.split('-'))
    if not 1970 <= year <= 9998:
        raise ValueError('Unsupported month year')
    return year * 12 + month - 1


def _month_text(index):
    year, month = divmod(index, 12)
    return f'{year:04d}-{month + 1:02d}'


def _month_ms(index):
    year, month = divmod(index, 12)
    return (datetime(year, month + 1, 1, tzinfo=timezone.utc)
            - datetime(1970, 1, 1, tzinfo=timezone.utc)).days * 86400000


@dataclass(frozen=True)
class BinanceSpotRequest:
    symbol: str
    interval: str
    start_month: str
    end_month: str
    as_of_ms: int

    def __post_init__(self):
        if type(self.symbol) is not str or not re.fullmatch(r'[A-Z0-9]{2,30}', self.symbol):
            raise ValueError('Invalid Binance spot symbol')
        if type(self.interval) is not str or self.interval not in INTERVALS:
            raise ValueError('Only supported fixed-duration spot intervals are allowed')
        integer(self.as_of_ms, 'as_of_ms')
        start, end = _month(self.start_month), _month(self.end_month)
        if not 0 <= end - start < 24:
            raise ValueError('Request requires 1..24 ascending months')
        if _month_ms(end + 1) > self.as_of_ms:
            raise ValueError('Requested months are not fully closed at the explicit cutoff')
        count = (_month_ms(end + 1) - _month_ms(start)) // INTERVALS[self.interval]
        if count > MAX_ROWS:
            raise ValueError('Requested range exceeds A007 candle limit')

    @property
    def source_label(self):
        return (f'Binance public spot klines {self.symbol} {self.interval} '
                f'{self.start_month}..{self.end_month}; provider checksum consistency only')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Archive redirects are not accepted')


def _download(url, limit):
    # Only internally constructed URLs are passed here; TLS verification stays on.
    if not url.startswith(ORIGIN + '/'):
        raise ValueError('Unexpected archive URL')
    opener = urllib.request.build_opener(_NoRedirect())
    request = urllib.request.Request(url, headers={'User-Agent': 'ARIYAN-A010-public-data/1'})
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError('Unexpected archive response')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Download exceeds byte limit')
    return raw


def _read(path, limit):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular, non-symlink snapshot file: ' + path.name)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Snapshot file exceeds byte limit: ' + path.name)
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _csv_from_archive(archive, checksum, name):
    if len(archive) > MAX_ARCHIVE_BYTES or len(checksum) > 512:
        raise ValueError('Archive/checksum exceeds byte limit')
    match = re.fullmatch(r'([0-9a-fA-F]{64})[ \t]+\*?' + re.escape(name) + r'\r?\n?',
                        checksum.decode('ascii'))
    if not match or match[1].lower() != _sha(archive):
        raise ValueError('Published checksum name/digest does not match archive')
    with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
        members = zipped.infolist()
        if len(members) != 1 or members[0].filename != name[:-4] + '.csv':
            raise ValueError('Archive must contain exactly its expected CSV member')
        member = members[0]
        if (member.flag_bits & 1 or member.file_size > MAX_BYTES
                or member.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
            raise ValueError('Unsupported or oversized ZIP member')
        with zipped.open(member) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or len(raw) != member.file_size:
            raise ValueError('Invalid uncompressed CSV size')
    return raw


def _build(request, stage, *, existing=None, progress=None):
    if type(request) is not BinanceSpotRequest:
        raise ValueError('A BinanceSpotRequest is required')
    entries = []
    source_bytes = 0
    canonical = stage / 'candles.csv'
    with canonical.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, lineterminator='\n')
        writer.writerow(HEADER)
        for month_index in range(_month(request.start_month), _month(request.end_month) + 1):
            month = _month_text(month_index)
            stem = f'{request.symbol}-{request.interval}-{month}'
            archive_name = stem + '.zip'
            url = f'{ORIGIN}/{request.symbol}/{request.interval}/{archive_name}'
            if existing is None:
                checksum = _download(url + '.CHECKSUM', 512)
                archive = _download(url, MAX_ARCHIVE_BYTES)
            else:
                checksum = _read(existing / (archive_name + '.CHECKSUM'), 512)
                archive = _read(existing / archive_name, MAX_ARCHIVE_BYTES)
            raw = _csv_from_archive(archive, checksum, archive_name)
            source_bytes += len(raw) + len(archive) + len(checksum)
            if source_bytes > MAX_SOURCE_BYTES:
                raise ValueError('Combined source bytes exceed 64 MiB limit')
            csv_name = stem + '.csv'
            if existing is None:
                for name, content in ((archive_name, archive),
                                      (archive_name + '.CHECKSUM', checksum), (csv_name, raw)):
                    (stage / name).write_bytes(content)
                raw_path = stage / csv_name
            else:
                raw_path = existing / csv_name
                if _read(raw_path, MAX_BYTES) != raw:
                    raise ValueError('Stored source CSV differs from verified archive')
            unit = 'us' if month_index >= _month('2025-01') else 'ms'
            dataset = load_candles(raw_path, symbol=request.symbol,
                                   interval_ms=INTERVALS[request.interval], source=request.source_label,
                                   as_of_ms=request.as_of_ms, input_format='binance-spot',
                                   timestamp_unit=unit)
            first, end = _month_ms(month_index), _month_ms(month_index + 1)
            if (dataset.candles[0].timestamp_ms != first
                    or dataset.candles[-1].timestamp_ms + dataset.interval_ms != end
                    or len(dataset.candles) != (end - first) // dataset.interval_ms):
                raise ValueError('Source CSV does not cover the complete requested UTC month')
            for candle in dataset.candles:
                writer.writerow([candle.timestamp_ms, candle.open, candle.high,
                                 candle.low, candle.close, candle.volume])
            if stream.tell() > MAX_BYTES:
                raise ValueError('Canonical CSV exceeds A007 byte limit')
            entries.append({
                'month': month, 'archive_file': archive_name, 'archive_url': url,
                'checksum_file': archive_name + '.CHECKSUM', 'checksum_url': url + '.CHECKSUM',
                'archive_sha256': _sha(archive), 'checksum_sha256': _sha(checksum),
                'published_archive_checksum_matched': True,
                'csv_file': csv_name, 'csv_sha256': dataset.raw_sha256,
                'timestamp_unit': unit, 'candles': len(dataset.candles),
            })
            if progress is not None:
                progress(month, len(dataset.candles))
    dataset = load_candles(canonical, symbol=request.symbol,
                           interval_ms=INTERVALS[request.interval], source=request.source_label,
                           as_of_ms=request.as_of_ms)
    return {
        'version': 'ARIYAN-A010-BINANCE-SPOT-SNAPSHOT-V1',
        'mode': 'PUBLIC_DATA_INTAKE_NO_EVALUATION_OR_ORDERS',
        'request': asdict(request), 'provider_documentation': DOCUMENTATION,
        'instrument': {'asset_class': 'CRYPTO', 'venue': 'BINANCE',
                       'market_type': 'SPOT', 'symbol': request.symbol},
        'source_label': request.source_label,
        'source_independently_authenticated': False, 'live_authorized': False,
        'dataset': {'file': 'candles.csv', 'input_format': 'canonical', 'timestamp_unit': 'ms',
                    'raw_sha256': dataset.raw_sha256, 'interval_ms': dataset.interval_ms,
                    'candles': len(dataset.candles),
                    'first_open_ms': dataset.candles[0].timestamp_ms,
                    'last_close_ms': dataset.candles[-1].timestamp_ms + dataset.interval_ms},
        'archives': entries,
        'limitations': [
            'Provider checksums confirm byte consistency, not independent market-data truth.',
            'Archive filenames and provider labels do not independently prove instrument identity.',
            'Provider archives may later change; retained original bytes identify this snapshot.',
            'No independent price-source comparison or economic outlier screening.',
            'No performance evaluation, statistical adequacy, unseen-data or profitability claim.',
            'Snapshot and local acquisition time are unsigned and can be coherently recreated.',
            'Spot-only adapter; other venues, exchange sessions and derivatives need separate adapters.',
            'No credentials, orders, leverage, portfolio allocation or live trading authority.',
        ],
    }


def _json(value):
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n'


def acquire_snapshot(request, output, *, progress=None):
    if type(request) is not BinanceSpotRequest:
        raise ValueError('A BinanceSpotRequest is required')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Snapshot destination already exists')
    # Build in an owned temporary directory; publish only after all validation.
    with tempfile.TemporaryDirectory(prefix='.atai-a010-', dir=output.parent) as temp:
        stage = Path(temp)
        manifest = _build(request, stage, progress=progress)
        manifest['acquired_at_utc'] = datetime.now(timezone.utc).isoformat()
        (stage / 'SOURCE.json').write_text(_json(manifest), encoding='utf-8')
        output.mkdir()  # Exclusive even if another process created it during download.
        written = []
        try:
            # SOURCE.json is the last file; an interrupted copy is not a valid bundle.
            paths = sorted(p for p in stage.iterdir() if p.name != 'SOURCE.json')
            paths.append(stage / 'SOURCE.json')
            for source in paths:
                target = output / source.name
                with target.open('xb') as stream, source.open('rb') as incoming:
                    written.append(target)
                    shutil.copyfileobj(incoming, stream)
        except BaseException:
            for path in reversed(written):
                path.unlink()
            try:
                output.rmdir()
            except OSError:
                pass
            raise
    return manifest


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest key')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Non-finite manifest constant')


def verify_snapshot(folder):
    folder = Path(folder)
    manifest = json.loads(_read(folder / 'SOURCE.json', MAX_MANIFEST_BYTES).decode('utf-8'),
                          object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(manifest) is not dict:
        raise ValueError('Snapshot manifest must be an object')
    try:
        request = BinanceSpotRequest(**manifest['request'])
        acquired = manifest['acquired_at_utc']
        if (type(acquired) is not str or
                datetime.fromisoformat(acquired).utcoffset().total_seconds() != 0):
            raise ValueError('Acquisition timestamp must include UTC timezone')
        with tempfile.TemporaryDirectory(prefix='atai-a010-verify-') as temp:
            stage = Path(temp)
            expected = _build(request, stage, existing=folder)
            expected['acquired_at_utc'] = acquired
            if (_json(manifest) != _json(expected)
                    or _read(folder / 'candles.csv', MAX_BYTES) != (stage / 'candles.csv').read_bytes()):
                raise ValueError('Snapshot files or manifest differ from validated source')
        names = {'SOURCE.json', 'candles.csv'}
        for entry in expected['archives']:
            names.update((entry['archive_file'], entry['checksum_file'], entry['csv_file']))
        if {p.name for p in folder.iterdir()} != names:
            raise ValueError('Snapshot contains unexpected or missing files')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed snapshot manifest') from exc
    return expected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    fetch = commands.add_parser('fetch')
    fetch.add_argument('--symbol', required=True)
    fetch.add_argument('--interval', choices=INTERVALS, default='1h')
    fetch.add_argument('--start-month', required=True)
    fetch.add_argument('--end-month', required=True)
    fetch.add_argument('--as-of-ms', required=True, type=int)
    fetch.add_argument('--output-dir', required=True, type=Path)
    verify = commands.add_parser('verify')
    verify.add_argument('--snapshot', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == 'fetch':
            request = BinanceSpotRequest(args.symbol, args.interval, args.start_month,
                                         args.end_month, args.as_of_ms)
            manifest = acquire_snapshot(request, args.output_dir, progress=lambda month, count:
                print(f'Validated source month {month}: {count} candles', flush=True))
        else:
            manifest = verify_snapshot(args.snapshot)
        print('A010 SNAPSHOT VALIDATED — NO PERFORMANCE EVALUATION OR LIVE ACTIONS')
        print('Symbol:', manifest['request']['symbol'])
        print('Candles:', manifest['dataset']['candles'])
        print('Canonical CSV SHA256:', manifest['dataset']['raw_sha256'])
    except (OSError, ValueError, TypeError, ArithmeticError, UnicodeError, csv.Error,
            zipfile.BadZipFile, RuntimeError, RecursionError) as exc:
        parser.exit(2, f'Snapshot rejected: {exc}\n')
    return 0


if __name__ == '__main__':
    main()
