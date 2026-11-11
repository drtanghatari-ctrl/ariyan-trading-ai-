"""Synthetic prices and schedules only; hand-computed expectations."""
import unittest
from datetime import date, datetime, time, timezone
from decimal import Decimal as D

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.session_candles import (
    SessionCandleDataset, daily_session_schedule, slice_dataset, weekly_session_schedule,
)
from ariyan_trading.sessions import CoverageKind, IntervalStatus, SessionSchedule, SessionWindow
from ariyan_trading.strategies import BuyAndHold

I = 60000


def spec():
    return MarginInstrumentSpec(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'SES-001'), display_symbol='SYNTH',
        asset_class=A.INDEX, product=P.CFD, base_label='SYNTHETIC index', quote_currency='USD',
        contract_size='1000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
        price_step='0.01', pip_size='0.01', initial_margin_rate='0.1',
        maintenance_margin_rate='0.05', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-SESSIONS-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=0, effective_until_ms=None,
        source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)


def schedule(kind=CoverageKind.EXHAUSTIVE):
    # Two sessions of three one-minute slots: slots 0..2 and 10..12; slots 3..9 are closed.
    return SessionSchedule('SYNTHETIC-SESSIONS', 'UTC', 0, 13 * I, kind,
                           (SessionWindow(0, 3 * I, 'S1'), SessionWindow(10 * I, 13 * I, 'S2')),
                           'SYNTHETIC TEST ONLY', 1)


def bars(slots_prices, sched=None, **kwargs):
    candles = tuple(Candle(s * I, D(o), D(h), D(l), D(c), D(1)) for s, (o, h, l, c) in slots_prices)
    return SessionCandleDataset(candles, 'SYNTH', I, 'SYNTHETIC TEST ONLY', 13 * I, 'c' * 64,
                                sched or schedule(), **kwargs)


def px(p):
    return (p, p, p, p)


FULL = [(0, px(100)), (1, px(100)), (2, px(100)), (10, px(100)), (11, px(100)), (12, px(100))]


class SessionDatasetA037Tests(unittest.TestCase):
    def test_gap_outside_sessions_is_accepted(self):
        ds = bars(FULL)
        self.assertEqual(len(ds.candles), 6)

    def test_missing_candle_inside_a_session_is_rejected(self):
        with self.assertRaises(ValueError):
            bars([(0, px(100)), (2, px(100)), (10, px(100)), (11, px(100))])

    def test_candle_outside_every_session_is_rejected(self):
        with self.assertRaises(ValueError):
            bars([(0, px(100)), (1, px(100)), (5, px(100)), (10, px(100))])

    def test_partial_coverage_cannot_prove_a_gap_is_closed(self):
        with self.assertRaises(ValueError):
            bars(FULL, schedule(CoverageKind.PARTIAL))
        # contiguous data inside one session needs no gap proof
        bars([(0, px(100)), (1, px(100)), (2, px(100))], schedule(CoverageKind.PARTIAL))

    def test_gap_beyond_coverage_is_rejected(self):
        short = SessionSchedule('S', 'UTC', 0, 8 * I, CoverageKind.EXHAUSTIVE,
                                (SessionWindow(0, 3 * I, 'S1'),), 'SYNTHETIC', 1)
        with self.assertRaises(ValueError):
            bars([(0, px(100)), (1, px(100)), (11, px(100))], short)

    def test_unordered_unaligned_and_future_candles_are_rejected(self):
        for rows, extra in (([(1, px(100)), (0, px(100))], {}), ([(0, px(100)), (0, px(100))], {}),
                            ([(0, px(100)), (1, px(100))], {'anchor_ms': 5})):
            with self.assertRaises(ValueError):
                bars(rows, **extra)
        candles = (Candle(11 * I, D(1), D(1), D(1), D(1), D(1)), Candle(12 * I, D(1), D(1), D(1), D(1), D(1)))
        with self.assertRaises(ValueError):
            SessionCandleDataset(candles, 'SYNTH', I, 'S', 12 * I + 5, 'c' * 64, schedule())

    def test_slice_keeps_type_and_provenance(self):
        ds = bars(FULL)
        part = slice_dataset(ds, 3, 6)
        self.assertIsInstance(part, SessionCandleDataset)
        self.assertEqual((part.raw_sha256, len(part.candles)), ('c' * 64, 3))
        plain = CandleDataset(tuple(Candle(i * I, D(1), D(1), D(1), D(1), D(1)) for i in range(5)),
                              'SYNTH', I, 'S', 5 * I, 'd' * 64, 'canonical', 'ms')
        self.assertIsInstance(slice_dataset(plain, 1, 4), CandleDataset)
        for bounds in ((-1, 2), (3, 3), (0, 99), ('a', 2)):
            with self.assertRaises(ValueError):
                slice_dataset(ds, *bounds)


class SessionBacktestA037Tests(unittest.TestCase):
    CONFIG = dict(margin_fraction='0.5', financing_long_per_lot_per_bar='1')

    def test_position_is_held_across_the_closure_and_financing_basis_matters(self):
        by_bar = run_backtest(bars(FULL), spec(), BuyAndHold(), BacktestConfig(**self.CONFIG))
        t, = by_bar.trades
        self.assertEqual((t.lots, t.open_ms), (D('0.5'), I))
        self.assertEqual(t.financing, D('2.5'))     # 5 bars held x 0.5 lots
        elapsed = run_backtest(bars(FULL), spec(), BuyAndHold(),
                               BacktestConfig(financing_basis='ELAPSED', **self.CONFIG))
        # slots 1, 2, then 8 grid slots to reach slot 10, then 11, 12 = 12 units
        self.assertEqual(elapsed.trades[0].financing, D('6.0'))

    def test_gap_down_through_the_closure_is_not_smoothed(self):
        rows = [(0, px(100)), (1, px(100)), (2, px(100)), (10, px(50)), (11, px(50)), (12, px(50))]
        r = run_backtest(bars(rows), spec(), BuyAndHold(), BacktestConfig(margin_fraction='0.5'))
        t, = r.trades
        self.assertEqual((t.reason, t.close_ms, t.exit_price), ('STOP_OUT', 10 * I, D(50)))
        self.assertEqual(t.gross_pnl, D(-25000))  # 50 points x 0.5 lots x 1000
        self.assertTrue(r.metrics['ruined'])
        self.assertEqual(r.metrics['final_equity'], '-15000.000000')

    def test_decisions_across_the_gap_fill_at_the_first_open_after_it(self):
        from ariyan_trading.strategies import Signal, Strategy

        class FlatThenLong(Strategy):
            name = 'flat_then_long'
            lookback = 1

            def target(self, history):
                return Signal.LONG if history[-1].timestamp_ms >= 2 * I else Signal.FLAT

        r = run_backtest(bars(FULL), spec(), FlatThenLong(), BacktestConfig(margin_fraction='0.5'))
        self.assertEqual(r.trades[0].open_ms, 10 * I)  # decision at slot 2 close; next bar is slot 10

    def test_record_carries_schedule_fingerprint(self):
        ds = bars(FULL)
        r = run_backtest(ds, spec(), BuyAndHold(), BacktestConfig(margin_fraction='0.5'))
        self.assertEqual(r.provenance['session_schedule_sha256'], schedule().fingerprint())
        plain = CandleDataset(tuple(Candle(i * I, D(1), D(1), D(1), D(1), D(1)) for i in range(5)),
                              'SYNTH', I, 'S', 5 * I, 'd' * 64, 'canonical', 'ms')
        self.assertIsNone(run_backtest(plain, spec(), BuyAndHold()).provenance['session_schedule_sha256'])

    def test_invalid_financing_basis(self):
        with self.assertRaises(ValueError):
            BacktestConfig(financing_basis='WEEKLY')


def utc(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000)


class ScheduleBuildersA037Tests(unittest.TestCase):
    def test_daily_schedule_is_dst_aware_with_holidays_and_early_closes(self):
        s = daily_session_schedule(
            'SYNTHETIC-NYSE-LIKE', 'America/New_York', (0, 1, 2, 3, 4), time(9, 30), time(16, 0),
            date(2026, 3, 2), date(2026, 3, 13), 'SYNTHETIC TEST ONLY', 1,
            holidays={date(2026, 3, 4)}, early_closes={date(2026, 3, 6): time(13, 0)})
        windows = {w.session_label: w for w in s.windows}
        self.assertEqual(len(windows), 9)  # ten weekdays minus the holiday
        self.assertNotIn('DAILY-2026-03-04', windows)
        mon = windows['DAILY-2026-03-02']  # still EST (UTC-5)
        self.assertEqual((mon.open_ms, mon.close_ms), (utc(2026, 3, 2, 14, 30), utc(2026, 3, 2, 21, 0)))
        mon2 = windows['DAILY-2026-03-09']  # EDT began on 2026-03-08 (UTC-4)
        self.assertEqual((mon2.open_ms, mon2.close_ms), (utc(2026, 3, 9, 13, 30), utc(2026, 3, 9, 20, 0)))
        self.assertEqual(windows['DAILY-2026-03-06'].close_ms, utc(2026, 3, 6, 18, 0))
        self.assertIs(s.coverage_kind, CoverageKind.EXHAUSTIVE)
        self.assertIs(s.classify_interval(utc(2026, 3, 2, 14, 30), utc(2026, 3, 2, 14, 31)),
                      IntervalStatus.WITHIN_SESSION)
        self.assertIs(s.classify_interval(utc(2026, 3, 7, 15, 0), utc(2026, 3, 7, 15, 1)),
                      IntervalStatus.DECLARED_CLOSED)  # Saturday
        self.assertIs(s.classify_interval(utc(2026, 3, 4, 15, 0), utc(2026, 3, 4, 15, 1)),
                      IntervalStatus.DECLARED_CLOSED)  # holiday

    def test_weekly_forex_style_schedule_crosses_the_dst_change(self):
        s = weekly_session_schedule(
            'SYNTHETIC-FX-WEEK', 'America/New_York', 6, time(17, 0), 4, time(17, 0),
            date(2026, 3, 2), date(2026, 3, 20), 'SYNTHETIC TEST ONLY', 1)
        spans = {(w.open_ms, w.close_ms) for w in s.windows}
        self.assertIn((utc(2026, 3, 8, 21, 0), utc(2026, 3, 13, 21, 0)), spans)  # Sun EDT -> Fri EDT
        self.assertIn((utc(2026, 3, 15, 21, 0), utc(2026, 3, 20, 21, 0)), spans)
        first = min(s.windows, key=lambda w: w.open_ms)  # opens Sun 03-01 EST, clipped to coverage
        self.assertEqual(first.open_ms, s.coverage_start_ms)
        self.assertEqual(first.close_ms, utc(2026, 3, 6, 22, 0))  # Fri 17:00 EST
        self.assertIs(s.classify_interval(utc(2026, 3, 14, 12, 0), utc(2026, 3, 14, 12, 1)),
                      IntervalStatus.DECLARED_CLOSED)  # Saturday
        self.assertIs(s.classify_interval(utc(2026, 3, 11, 12, 0), utc(2026, 3, 11, 12, 1)),
                      IntervalStatus.WITHIN_SESSION)

    def test_builder_inputs_are_validated(self):
        base = ('S', 'America/New_York', (0,), time(9), time(10), date(2026, 3, 2), date(2026, 3, 6),
                'SYNTHETIC', 1)
        daily_session_schedule(*base)
        for index, value in ((1, 'Nowhere/Land'), (2, ()), (2, (7,)), (3, time(11)), (6, date(2026, 3, 1)),
                             (4, 'x')):
            args = list(base)
            args[index] = value
            with self.assertRaises(ValueError):
                daily_session_schedule(*args)
        with self.assertRaises(ValueError):
            daily_session_schedule(*base, early_closes={date(2026, 3, 2): time(8)})
        with self.assertRaises(ValueError):
            weekly_session_schedule('S', 'Nowhere/Land', 6, time(17), 4, time(17), date(2026, 3, 2),
                                    date(2026, 3, 6), 'SYNTHETIC', 1)
        with self.assertRaises(ValueError):
            weekly_session_schedule('S', 'UTC', 7, time(17), 4, time(17), date(2026, 3, 2),
                                    date(2026, 3, 6), 'SYNTHETIC', 1)

    def test_a_built_schedule_validates_real_shaped_gaps(self):
        s = weekly_session_schedule('SYNTHETIC-FX-WEEK', 'UTC', 0, time(0, 0), 4, time(22, 0),
                                    date(2026, 3, 2), date(2026, 3, 15), 'SYNTHETIC', 1)
        hour = 3_600_000
        friday_last = utc(2026, 3, 6, 21)
        monday_first = utc(2026, 3, 9, 0)
        rows = [(friday_last - hour, 1), (friday_last, 1), (monday_first, 1), (monday_first + hour, 1)]
        candles = tuple(Candle(t, D(100), D(100), D(100), D(100), D(1)) for t, _ in rows)
        ds = SessionCandleDataset(candles, 'SYNTH', hour, 'SYNTHETIC', monday_first + 2 * hour,
                                  'e' * 64, s)
        self.assertEqual(len(ds.candles), 4)
        bad = candles[:2] + (Candle(utc(2026, 3, 7, 3), D(100), D(100), D(100), D(100), D(1)),)
        with self.assertRaises(ValueError):
            SessionCandleDataset(bad, 'SYNTH', hour, 'SYNTHETIC', monday_first, 'e' * 64, s)


if __name__ == '__main__':
    unittest.main()
