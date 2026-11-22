"""A041 importer tests. Synthetic prices only; formats mimic real exports, data is invented."""
import hashlib
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.fx_csv import DAY_MS, load_fx_csv
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.strategies import SmaCross

HOUR = 3_600_000


def utc_ms(y, m, d, h=0):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def price(i):
    base = D('1.10000') + D(i % 17) * D('0.00050') - D(i % 5) * D('0.00020')
    return base, base + D('0.00100'), base - D('0.00100'), base + D('0.00030')


def weekdays(start, count):
    days, day = [], start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


class FxCsvTests(unittest.TestCase):
    def write(self, text):
        handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, newline='', encoding='utf-8')
        handle.write(text)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def daily_text(self, header, fmt, days, extra=''):
        lines = [header]
        for i, day in enumerate(days):
            o, h, l, c = price(i)
            lines.append(fmt(day, o, h, l, c) + extra)
        return '\n'.join(lines) + '\n'

    def test_stooq_style_daily_without_volume(self):
        days = weekdays(date(2024, 1, 2), 40)
        text = self.daily_text('Date,Open,High,Low,Close', lambda d, o, h, l, c: f'{d},{o},{h},{l},{c}', days)
        ds, rep = load_fx_csv(self.write(text), symbol='EURUSD', source='synthetic stooq-like')
        self.assertEqual(len(ds.candles), 39)              # last candle dropped by default
        self.assertTrue(rep.dropped_last_candle)
        self.assertEqual(ds.interval_ms, DAY_MS)
        self.assertEqual(ds.candles[0].timestamp_ms, utc_ms(2024, 1, 2))
        self.assertEqual(ds.candles[0].volume, 0)
        self.assertEqual(len(rep.runs), 1)                 # weekends accepted as declared closures
        self.assertEqual(rep.raw_sha256, hashlib.sha256(text.encode()).hexdigest())

    def test_yahoo_style_with_adj_close_and_null_row(self):
        days = weekdays(date(2024, 1, 2), 60)
        lines = ['Date,Open,High,Low,Close,Adj Close,Volume']
        for i, day in enumerate(days):
            if i == 40:
                lines.append(f'{day},null,null,null,null,null,null')
                continue
            o, h, l, c = price(i)
            lines.append(f'{day},{o},{h},{l},{c},{c},0')
        path = self.write('\n'.join(lines) + '\n')
        with self.assertRaisesRegex(ValueError, 'CSV line 42'):
            load_fx_csv(path, symbol='EURUSD', source='s')
        ds, rep = load_fx_csv(path, symbol='EURUSD', source='s', on_bad_row='skip')
        self.assertEqual(len(rep.skipped_rows), 1)
        self.assertEqual(rep.skipped_rows[0][0], 42)
        self.assertEqual(len(rep.runs), 2)                 # the missing weekday splits the data
        self.assertEqual(rep.kept_run[2], 40)              # longest run is kept, not stitched
        self.assertEqual(len(ds.candles), 40)
        with self.assertRaisesRegex(ValueError, 'gap-free runs'):
            load_fx_csv(path, symbol='EURUSD', source='s', on_bad_row='skip', keep_longest_run=False)

    def test_mt5_tab_export_with_server_offset(self):
        # Two forex weeks in January (New York winter): Sun 22:00 UTC to Fri 22:00 UTC.
        stamps = []
        for week_start in (utc_ms(2024, 1, 7, 22), utc_ms(2024, 1, 14, 22)):
            stamps += [week_start + k * HOUR for k in range(120)]     # exactly five days
        lines = ['<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>']
        for i, s in enumerate(stamps):
            server = datetime.fromtimestamp(s / 1000 + 2 * 3600, timezone.utc)   # server is GMT+2
            o, h, l, c = price(i)
            lines.append(f"{server:%Y.%m.%d}\t{server:%H:%M:%S}\t{o}\t{h}\t{l}\t{c}\t10\t0\t12")
        path = self.write('\n'.join(lines) + '\n')
        ds, rep = load_fx_csv(path, symbol='EURUSD', source='synthetic mt5-like', utc_offset_minutes=120)
        self.assertEqual(ds.interval_ms, HOUR)
        self.assertEqual(ds.candles[0].timestamp_ms, utc_ms(2024, 1, 7, 22))
        self.assertEqual(len(rep.runs), 1)                 # the 48-hour weekend is a declared closure
        self.assertEqual(rep.dropped_outside_session, 0)
        # The same file read as UTC lands two hours later and falls partly outside the session.
        _, shifted = load_fx_csv(path, symbol='EURUSD', source='s', utc_offset_minutes=0)
        self.assertGreater(shifted.dropped_outside_session, 0)

    def test_dukascopy_style_and_newest_first_order(self):
        rows = []
        for i in range(30):
            when = datetime(2024, 1, 8, 0, tzinfo=timezone.utc) + timedelta(hours=i)
            o, h, l, c = price(i)
            rows.append(f'{when:%d.%m.%Y %H:%M:%S}.000,{o},{h},{l},{c},1.5')
        text = 'Gmt time,Open,High,Low,Close,Volume\n' + '\n'.join(reversed(rows)) + '\n'
        ds, _ = load_fx_csv(self.write(text), symbol='EURUSD', source='synthetic dukascopy-like')
        self.assertEqual(ds.candles[0].timestamp_ms, utc_ms(2024, 1, 8))
        self.assertEqual(ds.candles[0].volume, D('1.5'))
        self.assertLess(ds.candles[0].timestamp_ms, ds.candles[1].timestamp_ms)

    def test_saturday_bar_is_dropped_and_counted(self):
        rows = []
        for i in range(24 * 3):
            when = datetime(2024, 1, 8, 0, tzinfo=timezone.utc) + timedelta(hours=i)
            o, h, l, c = price(i)
            rows.append(f'{when:%Y-%m-%d %H:%M:%S},{o},{h},{l},{c},0')
        sat = datetime(2024, 1, 13, 10, tzinfo=timezone.utc)
        rows.append(f'{sat:%Y-%m-%d %H:%M:%S},1.1,1.2,1.0,1.1,0')
        text = 'Time,Open,High,Low,Close,Volume\n' + '\n'.join(rows) + '\n'
        ds, rep = load_fx_csv(self.write(text), symbol='EURUSD', source='s')
        self.assertEqual(rep.dropped_outside_session, 0)   # Saturday bar became the (dropped) last row
        text2 = text + f'{sat + timedelta(hours=1):%Y-%m-%d %H:%M:%S},1.1,1.2,1.0,1.1,0\n'
        ds2, rep2 = load_fx_csv(self.write(text2), symbol='EURUSD', source='s')
        self.assertEqual(rep2.dropped_outside_session, 1)
        self.assertEqual(len(ds2.candles), len(ds.candles))

    def test_christmas_and_new_year_are_declared_closures_for_daily_bars(self):
        days = [d for d in weekdays(date(2023, 12, 18), 20) if d not in (date(2023, 12, 25), date(2024, 1, 1))]
        text = self.daily_text('Date,Open,High,Low,Close', lambda d, o, h, l, c: f'{d},{o},{h},{l},{c}', days)
        path = self.write(text)
        ds, rep = load_fx_csv(path, symbol='EURUSD', source='s')
        self.assertEqual(len(rep.runs), 1)                         # one run across both holidays
        self.assertEqual(len(ds.candles), len(days) - 1)
        _, split = load_fx_csv(path, symbol='EURUSD', source='s', holidays=())
        self.assertEqual(len(split.runs), 3)                       # undeclared holidays split the data

    def test_rejections(self):
        days = weekdays(date(2024, 1, 1), 10)
        good = self.daily_text('Date,Open,High,Low,Close', lambda d, o, h, l, c: f'{d},{o},{h},{l},{c}', days)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            load_fx_csv(self.write(good + good.split('\n')[1] + '\n'), symbol='EURUSD', source='s')
        bad = good.replace('Date,Open,High,Low,Close', 'Date,Open,High,Low,Close', 1).split('\n')
        bad[3] = '2024-01-03,1.10000,1.09000,1.12000,1.10000'    # high below low
        with self.assertRaisesRegex(ValueError, 'CSV line 4'):
            load_fx_csv(self.write('\n'.join(bad)), symbol='EURUSD', source='s')
        with self.assertRaisesRegex(ValueError, 'no close column'):
            load_fx_csv(self.write('Date,Open,High,Low\n2024-01-01,1,1,1\n'), symbol='EURUSD', source='s')
        with self.assertRaisesRegex(ValueError, 'Unknown timezone'):
            load_fx_csv(self.write(good), symbol='EURUSD', source='s', timezone_name='Mars/Base')
        with self.assertRaisesRegex(ValueError, 'not both'):
            load_fx_csv(self.write(good), symbol='EURUSD', source='s', timezone_name='UTC', utc_offset_minutes=0)

    def test_imported_daily_data_runs_through_the_backtester(self):
        days = weekdays(date(2023, 1, 2), 260)
        text = self.daily_text('Date,Open,High,Low,Close', lambda d, o, h, l, c: f'{d},{o},{h},{l},{c}', days)
        ds, _ = load_fx_csv(self.write(text), symbol='EURUSD', source='synthetic')
        spec = MarginInstrumentSpec(
            identity=InstrumentIdentity('SYNTHETIC-BROKER', 'FX-001'), display_symbol='EURUSD',
            asset_class=A.FOREX, product=P.FX_MARGIN, base_label='EUR', quote_currency='USD',
            contract_size='100000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
            price_step='0.00001', pip_size='0.0001', initial_margin_rate='0.02',
            maintenance_margin_rate='0.01', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
            commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-SESSIONS-V1',
            timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
            effective_from_ms=0, effective_until_ms=None, source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)
        result = run_backtest(ds, spec, SmaCross(5, 20, allow_short=True),
                              BacktestConfig(opening_cash='10000', margin_fraction='0.1',
                                             spread='0.00010', financing_basis='ELAPSED'))
        self.assertIn('final_equity', result.metrics)


if __name__ == '__main__':
    unittest.main()
