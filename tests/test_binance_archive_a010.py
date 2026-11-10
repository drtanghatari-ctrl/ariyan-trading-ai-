"""Offline synthetic archive tests; fixtures are not historical market evidence."""
import calendar
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from symlink_fixture import symlink_or_skip

from ariyan_trading import binance_archive as module
from ariyan_trading.dataset_plan import build_dataset_plan, verify_dataset_plan
from ariyan_trading.market_data import load_candles

ROOT = Path(__file__).resolve().parents[1]

def ms(year, month, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp()) * 1000


def fixture(symbol, month, *, rows=None, extra=None, member=None):
    year, number = map(int, month.split('-'))
    scale = 1000 if year >= 2025 else 1
    if rows is None:
        rows = []
        for day in range(1, calendar.monthrange(year, number)[1] + 1):
            start = ms(year, number, day) * scale
            close = start + 86400000 * scale - 1
            rows.append(f'{start},100,110,90,105,1,{close},0,1,0,0,0')
    raw = ('\n'.join(rows) + '\n').encode()
    name = f'{symbol}-1d-{month}.zip'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member or name[:-4] + '.csv', raw)
        if extra:
            archive.writestr(extra, b'EXTRA')
    zipped = buffer.getvalue()
    checksum = f'{hashlib.sha256(zipped).hexdigest()}  {name}\n'.encode()
    url = f'{module.ORIGIN}/{symbol}/1d/{name}'
    return {url: zipped, url + '.CHECKSUM': checksum}, raw


class BinanceArchiveA010Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.parent = Path(temp.name)
        self.output = self.parent / 'snapshot'
        self.request = module.BinanceSpotRequest('BTCUSDT', '1d', '2024-12', '2025-01', ms(2025, 2))
        self.downloads = {}
        for month in ('2024-12', '2025-01'):
            self.downloads.update(fixture('BTCUSDT', month)[0])

    def acquire(self, downloads=None):
        data = self.downloads if downloads is None else downloads
        with patch.object(module, '_download', side_effect=lambda url, limit: data[url]):
            return module.acquire_snapshot(self.request, self.output)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'ariyan_trading.binance_archive', *map(str, args)],
            cwd=ROOT, env={**os.environ, 'PYTHONPATH': str(ROOT / 'app')}, capture_output=True, text=True)

    def test_two_months_cross_unit_boundary_complete_and_no_replay(self):
        with patch('ariyan_trading.replay.run_replay', side_effect=AssertionError('No replay')):
            manifest = self.acquire()
        self.assertEqual(manifest['dataset']['candles'], 62)
        self.assertEqual(manifest['dataset']['first_open_ms'], ms(2024, 12))
        self.assertEqual(manifest['dataset']['last_close_ms'], ms(2025, 2))
        self.assertEqual([x['timestamp_unit'] for x in manifest['archives']], ['ms', 'us'])
        self.assertEqual(len(list(self.output.iterdir())), 8)
        self.assertEqual(manifest['dataset']['raw_sha256'],
                         hashlib.sha256((self.output / 'candles.csv').read_bytes()).hexdigest())
        self.assertFalse(manifest['live_authorized'])
        self.assertFalse(manifest['source_independently_authenticated'])
        self.assertEqual(manifest['instrument']['market_type'], 'SPOT')
        with patch.object(module, '_download', side_effect=AssertionError('Offline verification')):
            self.assertEqual(module.verify_snapshot(self.output), manifest)

    def test_other_symbols_no_btc_hardcoding(self):
        for symbol in ('ETHUSDT', 'SOLUSDT'):
            request = replace(self.request, symbol=symbol, start_month='2025-01')
            downloads, _ = fixture(symbol, '2025-01')
            with patch.object(module, '_download', side_effect=lambda url, limit: downloads[url]):
                manifest = module.acquire_snapshot(request, self.parent / symbol)
            self.assertEqual(manifest['instrument']['symbol'], symbol)
            self.assertEqual(manifest['dataset']['candles'], 31)
            self.assertEqual(module.verify_snapshot(self.parent / symbol), manifest)

    def test_a009_plan_consumes_canonical_snapshot(self):
        manifest = self.acquire()
        dataset = load_candles(self.output / 'candles.csv', symbol='BTCUSDT',
            interval_ms=86400000, source=manifest['source_label'], as_of_ms=ms(2025, 2))
        plan = build_dataset_plan(dataset, development_candles=31)
        self.assertEqual(plan['dataset']['raw_sha256'], manifest['dataset']['raw_sha256'])
        self.assertEqual(plan['ranges'][1]['first_open_ms'], ms(2025, 1))
        self.assertEqual(verify_dataset_plan(dataset, plan), plan)

    def test_invalid_requests_before_network_or_output(self):
        options = [dict(symbol='../BTC'), dict(symbol='btc'), dict(symbol=True), dict(interval='1w'),
            dict(interval='1mo'), dict(interval='3d'), dict(interval=['1d']),
            dict(start_month='2025-1'), dict(start_month='2025-13'), dict(start_month='1969-12'),
            dict(start_month='2025-02'), dict(as_of_ms=True), dict(as_of_ms=ms(2025, 2)-1),
            dict(start_month='2022-01'), dict(interval='1m', start_month='2024-11')]
        with patch.object(module, '_download', side_effect=AssertionError('No network')):
            for kwargs in options:
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    module.acquire_snapshot(replace(self.request, **kwargs), self.output)
            with self.assertRaises(ValueError):
                module.acquire_snapshot({}, self.output)
        self.assertFalse(self.output.exists())

    def test_existing_destination_preserved_without_network(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.txt'
        sentinel.write_text('keep')
        with patch.object(module, '_download', side_effect=AssertionError('No network')):
            with self.assertRaises(ValueError):
                module.acquire_snapshot(self.request, self.output)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_checksum_mismatch_wrong_name_and_multiple_lines(self):
        key = next(url for url in self.downloads if url.endswith('.CHECKSUM'))
        for checksum in (b'0'*64 + b'  BTCUSDT-1d-2024-12.zip\n',
                         self.downloads[key].replace(b'BTCUSDT', b'ETHUSDT'),
                         self.downloads[key] + self.downloads[key], b'\xff'):
            downloads = dict(self.downloads)
            downloads[key] = checksum
            with self.subTest(checksum=checksum[:10]), self.assertRaises((ValueError, UnicodeError)):
                self.acquire(downloads)
            self.assertFalse(self.output.exists())
            self.assertEqual(list(self.parent.iterdir()), [])

    def test_unexpected_archive_members_and_corruption(self):
        for extra, member in (('../escape.csv', None), (None, '../escape.csv'),
                              ('extra.csv', None)):
            downloads = dict(self.downloads)
            downloads.update(fixture('BTCUSDT', '2024-12', extra=extra, member=member)[0])
            with self.assertRaises(ValueError):
                self.acquire(downloads)
            self.assertFalse(self.output.exists())
        downloads = dict(self.downloads)
        key = next(url for url in downloads if url.endswith('.zip'))
        downloads[key] = b'not a zip'
        downloads[key + '.CHECKSUM'] = (hashlib.sha256(downloads[key]).hexdigest()
            + '  BTCUSDT-1d-2024-12.zip\n').encode()
        with self.assertRaises(zipfile.BadZipFile):
            self.acquire(downloads)
        self.assertFalse((self.parent / 'escape.csv').exists())

    def test_missing_edge_gap_duplicate_bad_ohlc_and_wrong_units_rejected(self):
        raw = fixture('BTCUSDT', '2024-12')[1]
        rows = raw.decode().splitlines()
        cases = [rows[1:], rows[:-1], rows[:10]+rows[11:], rows[:10]+[rows[9]]+rows[10:],
                 [rows[0].replace(',100,110,90,105,', ',120,110,90,105,')]+rows[1:]]
        cases.append([line.replace(line.split(',')[0], str(int(line.split(',')[0])*1000), 1)
                      for line in rows])
        for lines in cases:
            downloads = dict(self.downloads)
            downloads.update(fixture('BTCUSDT', '2024-12', rows=lines)[0])
            with self.assertRaises(ValueError):
                self.acquire(downloads)
            self.assertFalse(self.output.exists())

    def test_bounds(self):
        for constant, limit in (('MAX_ARCHIVE_BYTES', 20), ('MAX_SOURCE_BYTES', 100), ('MAX_BYTES', 100)):
            with patch.object(module, constant, limit), self.assertRaises(ValueError):
                self.acquire()
            self.assertFalse(self.output.exists())

    def test_network_failure_rolls_back_owned_stage(self):
        calls = 0
        def download(url, limit):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('Synthetic network failure')
            return self.downloads[url]
        with patch.object(module, '_download', side_effect=download), self.assertRaises(OSError):
            module.acquire_snapshot(self.request, self.output)
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_publication_failure_cleans_partial_output(self):
        def fail(incoming, stream):
            stream.write(b'partial')
            raise OSError('Synthetic disk failure')
        with patch.object(module.shutil, 'copyfileobj', side_effect=fail), self.assertRaises(OSError):
            self.acquire()
        self.assertEqual(list(self.parent.iterdir()), [])

    def test_destination_race_does_not_overwrite(self):
        def download(url, limit):
            self.output.mkdir(exist_ok=True)
            (self.output / 'keep.txt').write_text('keep')
            return self.downloads[url]
        with patch.object(module, '_download', side_effect=download), self.assertRaises(FileExistsError):
            module.acquire_snapshot(self.request, self.output)
        self.assertEqual((self.output / 'keep.txt').read_text(), 'keep')
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_offline_verification_rejects_changed_files_and_types(self):
        manifest = self.acquire()
        files = ['candles.csv', manifest['archives'][0]['csv_file'],
                 manifest['archives'][0]['archive_file'], manifest['archives'][0]['checksum_file']]
        for name in files:
            path = self.output / name
            original = path.read_bytes()
            path.write_bytes(original + b'\n')
            with self.subTest(name=name), self.assertRaises((ValueError, zipfile.BadZipFile)):
                module.verify_snapshot(self.output)
            path.write_bytes(original)
        path = self.output / 'SOURCE.json'
        original = path.read_bytes()
        changed = copy.deepcopy(manifest)
        changed['live_authorized'] = 0
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            module.verify_snapshot(self.output)
        path.write_bytes(original)
        (self.output / 'unexpected').write_text('extra')
        with self.assertRaises(ValueError):
            module.verify_snapshot(self.output)

    def test_manifest_strictness_and_symlink_rejection(self):
        manifest = self.acquire()
        path = self.output / 'SOURCE.json'
        original = path.read_bytes()
        for raw in (b'{"request":1,"request":2}', b'{"x":NaN}', b'[]', b'{}',
                    b' ' * (module.MAX_MANIFEST_BYTES+1)):
            path.write_bytes(raw)
            with self.assertRaises(ValueError):
                module.verify_snapshot(self.output)
        path.write_bytes(original)
        with self.subTest(symlink='snapshot CSV'):
            csv_path = self.output / 'candles.csv'
            moved = self.parent / 'external.csv'
            csv_path.rename(moved)
            symlink_or_skip(csv_path, moved)
            with self.assertRaises(ValueError):
                module.verify_snapshot(self.output)

    def test_cli_offline_verify_and_invalid_fetch(self):
        self.acquire()
        result = self.cli('verify', '--snapshot', self.output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('62', result.stdout)
        (self.output / 'candles.csv').write_text('changed')
        self.assertEqual(self.cli('verify', '--snapshot', self.output).returncode, 2)
        result = self.cli('fetch', '--symbol', '../bad', '--start-month', '2025-01',
                          '--end-month', '2025-01', '--as-of-ms', ms(2025, 2),
                          '--output-dir', self.parent / 'absent')
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.parent / 'absent').exists())

    def test_https_fetch_is_bounded_and_rejects_redirects(self):
        url = next(iter(self.downloads))
        class Response(io.BytesIO):
            status = 200
            def geturl(self): return url
        opener = unittest.mock.Mock()
        opener.open.return_value = Response(b'12345')
        with patch.object(module.urllib.request, 'build_opener', return_value=opener):
            with self.assertRaises(ValueError):
                module._download(url, 4)
        with self.assertRaises(ValueError):
            module._download('http://example.invalid', 10)
        with self.assertRaises(ValueError):
            module._NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.invalid')

if __name__ == '__main__':
    unittest.main()
