"""A049 tests: read-only MT5 cost collection and Daily export, against a fake terminal."""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace as NS

from ariyan_trading.mt5_data import collect_costs, export_daily, find_symbols, swap_bp_per_day


def ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


class FakeMT5:
    TIMEFRAME_D1 = 16408

    def __init__(self, bars=300, gap=False):
        self.calls = []
        self.bars, self.gap = bars, gap

    def symbol_select(self, name, enable):
        self.calls.append(('select', name))
        return True

    def symbol_info(self, name):
        if name == 'NOPE':
            return None
        return NS(path='Forex\\' + name, description='desc', currency_base='EUR', currency_profit='USD',
                  currency_margin='EUR', digits=5, point=0.00001, trade_contract_size=100000.0, volume_min=0.01,
                  volume_step=0.01, volume_max=500.0, spread=10, spread_float=True, swap_mode=1, swap_long=-0.7,
                  swap_short=-1.0, swap_rollover3days=3, margin_initial=0.0, trade_calc_mode=0, trade_mode=4)

    def symbol_info_tick(self, name):
        return NS(bid=1.1000, ask=1.1002)

    def account_info(self):
        return NS(server='Test-Demo', trade_mode=0)

    def copy_rates_from_pos(self, name, tf, start, count):
        self.calls.append(('rates', name))
        rows, day = [], ts(2024, 1, 1)
        for i in range(min(count, self.bars)):
            if self.gap and i == 150:
                day += 20 * 86400
            rows.append({'time': day + i * 86400, 'open': 1.1 + i * 1e-5, 'high': 1.2, 'low': 1.0,
                         'close': 1.10001 + i * 1e-5 + 1e-12, 'tick_volume': 100 + i, 'real_volume': 0,
                         'spread': 10 + (i % 3)})
        return rows

    def symbols_get(self, group=''):
        return [NS(name='USOIL', description='Oil')] if 'OIL' in group else []

    def order_send(self, *a, **k):
        raise AssertionError('The data tool must never send orders')


class CostTests(unittest.TestCase):
    def test_swap_unit_conversion(self):
        self.assertAlmostEqual(swap_bp_per_day(1, -0.7, 0.00001, 100000, 1.1001), -0.0636, places=3)   # points
        self.assertAlmostEqual(swap_bp_per_day(5, -3.65, 0.01, 100, 3000), -1.0, places=9)             # percent/yr
        self.assertIsNone(swap_bp_per_day(4, -3.0, 0.01, 100, 3000))                                    # unit unsure
        self.assertIsNone(swap_bp_per_day(1, -1, 0.0001, 1, 0))                                         # no price

    def test_collect_costs_is_read_only_and_converts(self):
        mt5 = FakeMT5()
        out = collect_costs(mt5, ['EURUSD', 'NOPE'])
        self.assertEqual(out['server'], 'Test-Demo')
        eur, nope = out['symbols']
        self.assertFalse(nope['found'])
        self.assertEqual(eur['spread_median_daily_points_250d'], 11)
        self.assertAlmostEqual(eur['spread_bp_median_250d'], 11 * 0.00001 / 1.1001 * 1e4, places=4)
        self.assertAlmostEqual(eur['swap_long_bp_per_day'], -0.0636, places=3)
        self.assertAlmostEqual(eur['swap_short_bp_per_day'], -0.0909, places=3)
        self.assertEqual({c[0] for c in mt5.calls}, {'select', 'rates'})

    def test_find(self):
        self.assertEqual(find_symbols(FakeMT5(), ['*OIL*', '*XYZ*']), {'USOIL': 'Oil'})


class ExportTests(unittest.TestCase):
    def test_export_format_rounding_and_name(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = export_daily(FakeMT5(), 'EURUSD', folder)
            self.assertTrue(summary['ok'])
            self.assertEqual((summary['bars'], summary['first'], summary['largest_gap_days']), (300, '2024-01-01', 1))
            self.assertTrue(os.path.basename(summary['file']).startswith('EURUSD_Daily_202401010000_'))
            with open(summary['file'], encoding='utf-8') as stream:
                lines = stream.read().splitlines()
            self.assertEqual(lines[0], '<DATE>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>')
            cells = lines[1].split('\t')
            self.assertEqual(cells[0], '2024.01.01')
            self.assertEqual(cells[4], '1.10001')                  # float noise removed by fixed digits
            self.assertEqual(len(lines), 301)

    def test_gap_reported_and_short_history_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(export_daily(FakeMT5(gap=True), 'EURUSD', folder)['largest_gap_days'], 21)
            short = export_daily(FakeMT5(bars=50), 'EURUSD', folder)
            self.assertFalse(short['ok'])
            self.assertIn('scroll', short['reason'])
            self.assertFalse(export_daily(FakeMT5(), 'NOPE', folder)['ok'])

    def test_exported_file_loads_in_the_importer(self):
        from ariyan_trading.fx_csv import load_fx_csv
        with tempfile.TemporaryDirectory() as folder:
            summary = export_daily(FakeMT5(bars=300), 'EURUSD', folder)
            dataset, report = load_fx_csv(summary['file'], symbol='EURUSD', source='T', timezone_name='UTC',
                                          on_bad_row='raise')
            self.assertGreater(len(dataset.candles), 100)


if __name__ == '__main__':
    unittest.main()
