"""A048 tests: portfolio simulation causality, sizing, costs, drawdown control, buffer, conversion."""
import random
import unittest

from ariyan_trading.portfolio import (
    DAY_MS, Instrument, PortfolioConfig, _ret, common_calendar, simulate, signal,
)
from ariyan_trading.market_data import Candle, CandleDataset

CAL = [i * DAY_MS for i in range(520)]


def walk(seed, mu, sigma, n=520, start=100.0):
    rng, c = random.Random(seed), [start]
    for _ in range(n - 1):
        c.append(c[-1] * (1 + rng.gauss(mu, sigma)))
    o = [c[0]] + c[:-1]
    return o, c


def inst(symbol, cost=0.0, fin=0.0, inverse=False):
    return Instrument(symbol, cost, fin, inverse)


class CalendarAndMath(unittest.TestCase):
    def test_common_calendar(self):
        def ds(ts):
            cs = tuple(Candle(t, *(__import__('decimal').Decimal(1),) * 4, __import__('decimal').Decimal(1)) for t in ts)
            return CandleDataset(cs, 'X', DAY_MS, 'S', max(ts) + DAY_MS, 'a' * 64, 'canonical', 'ms')
        a, b = ds([0, DAY_MS, 2 * DAY_MS, 3 * DAY_MS]), ds([DAY_MS, 2 * DAY_MS, 3 * DAY_MS, 4 * DAY_MS])
        self.assertEqual(common_calendar([a, b]), [DAY_MS, 2 * DAY_MS, 3 * DAY_MS])
        self.assertEqual(common_calendar([a, b], end_ms=2 * DAY_MS), [DAY_MS, 2 * DAY_MS])

    def test_inverse_quote_return_and_signals(self):
        self.assertAlmostEqual(_ret(inst('A'), 100, 125), 0.25)
        self.assertAlmostEqual(_ret(inst('A', inverse=True), 100, 125), 0.2)
        up = [100 + i for i in range(300)]
        self.assertEqual(signal('mom252', up, 299), 1.0)
        self.assertEqual(signal('sma200', up, 299), 1.0)
        self.assertEqual(signal('mom_ens', up, 299), 1.0)
        down = list(reversed(up))
        self.assertEqual(signal('mom_ens', down, 299), -1.0)
        with self.assertRaises(ValueError):
            signal('nope', up, 299)


class Simulation(unittest.TestCase):
    def run_sim(self, series, instruments, name='mom252', **kw):
        return simulate(series, instruments, CAL, name, PortfolioConfig(**kw))

    def test_no_future_information(self):
        base = {'A': walk(1, 0.0008, 0.01), 'B': walk(2, 0.0, 0.015)}
        j = 400
        changed = {s: (o[:j + 1] + [x * 3 for x in o[j + 1:]], c[:j + 1] + [x * 3 for x in c[j + 1:]])
                   for s, (o, c) in base.items()}
        ins = [inst('A', 0.0001, 0.00005), inst('B', 0.0002, 0.00005)]
        r1, r2 = self.run_sim(base, ins), self.run_sim(changed, ins)
        early = lambda r: [(t, e) for t, e in r.equity_curve if t <= CAL[j]]
        self.assertGreater(len(early(r1)), 100)
        self.assertEqual(early(r1), early(r2))                       # prices after day j cannot change the past

    def test_riskier_instrument_gets_smaller_weight_and_gross_is_capped(self):
        series = {'CALM': walk(3, 0.0005, 0.003), 'WILD': walk(4, 0.0005, 0.03)}
        r = self.run_sim(series, [inst('CALM'), inst('WILD')], 'long')
        self.assertGreater(r.average_abs_weight['CALM'], 5 * r.average_abs_weight['WILD'])
        self.assertLessEqual(sum(r.average_abs_weight.values()), 3.0 + 1e-9)
        calm_only = {f'C{i}': walk(10 + i, 0.0, 0.0005) for i in range(5)}
        r = self.run_sim(calm_only, [inst(s) for s in calm_only], 'long', target_vol=0.5)
        self.assertLessEqual(sum(r.average_abs_weight.values()), 3.0 + 1e-6)

    def test_costs_and_financing_reduce_equity(self):
        series = {'A': walk(5, 0.001, 0.01), 'B': walk(6, 0.001, 0.012)}
        free = self.run_sim(series, [inst('A'), inst('B')], 'mom_ens')
        paid = self.run_sim(series, [inst('A', 0.001, 0.0001), inst('B', 0.001, 0.0001)], 'mom_ens')
        stressed = self.run_sim(series, [inst('A', 0.001, 0.0001), inst('B', 0.001, 0.0001)], 'mom_ens',
                                cost_mult=2, fin_mult=2)
        self.assertGreater(free.final_equity, paid.final_equity)
        self.assertGreater(paid.final_equity, stressed.final_equity)
        self.assertGreater(stressed.costs_paid, paid.costs_paid)
        self.assertEqual(free.costs_paid, 0.0)

    def test_gap_crash_triggers_a_halt_and_trading_resumes(self):
        o, c = walk(7, 0.0006, 0.002, n=520)
        for i in range(400, 520):                                    # one-day 25% crash, then calm
            c[i] *= 0.75
        o = [c[0]] + c[:-1]
        r = self.run_sim({'A': (o, c)}, [inst('A')], 'mom252')
        self.assertGreaterEqual(r.halts, 1)
        self.assertGreaterEqual(r.halted_bars, 20)

    def test_gradual_loss_is_contained_by_the_taper(self):
        c = walk(8, 0.0008, 0.002, n=520)[1]
        for i in range(380, 520):
            c[i] = c[i - 1] * 0.995                                  # steady 0.5% daily fall
        o = [c[0]] + c[:-1]
        def max_dd(result):
            peak, worst = 0.0, 0.0
            for _, e in result.equity_curve:
                peak = max(peak, e)
                worst = max(worst, 1 - e / peak)
            return worst
        stay_flat = self.run_sim({'A': (o, c)}, [inst('A')], 'long', halt_bars=10_000)
        free = self.run_sim({'A': (o, c)}, [inst('A')], 'long', dd_limit=0.99, brake_start=0.98)
        self.assertLess(max_dd(stay_flat), 0.13)                   # one episode: taper + halt keep it near 10%
        self.assertGreater(max_dd(free), max_dd(stay_flat) + 0.05)
        restarting = self.run_sim({'A': (o, c)}, [inst('A')], 'long')
        self.assertGreaterEqual(restarting.halts, 2)               # restarts re-enter a falling market ...
        self.assertGreater(max_dd(restarting), max_dd(stay_flat))  # ... so the all-time-high drawdown must be reported

    def test_buffer_reduces_trading(self):
        series = {'A': walk(9, 0.0007, 0.012), 'B': walk(11, 0.0007, 0.01)}
        ins = [inst('A'), inst('B')]
        loose = self.run_sim(series, ins, 'long', buffer=0.0)
        tight = self.run_sim(series, ins, 'long', buffer=0.25)
        self.assertLess(tight.position_changes, loose.position_changes)

    def test_validation(self):
        for kw in ({'target_vol': 0}, {'brake_start': 0.2, 'dd_limit': 0.1}, {'vol_window': 1}, {'cost_mult': -1}):
            with self.assertRaises(ValueError):
                PortfolioConfig(**kw)
        with self.assertRaises(ValueError):
            simulate({'A': walk(1, 0, 0.01, n=100)}, [inst('A')], CAL[:100], 'long')


if __name__ == '__main__':
    unittest.main()


class DirectionalFinancing(unittest.TestCase):
    def test_long_and_short_pay_different_financing(self):
        from ariyan_trading.portfolio import _fin_rate
        i = Instrument('X', 0.0, 0.0001, financing_long=0.0002, financing_short=-0.0001)
        self.assertEqual(_fin_rate(i, 1.0), 0.0002)
        self.assertEqual(_fin_rate(i, -1.0), -0.0001)
        self.assertEqual(_fin_rate(Instrument('Y', 0.0, 0.0003), -1.0), 0.0003)   # default: both directions

    def test_calendar_start_filter(self):
        from types import SimpleNamespace as N
        d = N(candles=[N(timestamp_ms=t) for t in (1, 2, 3, 4)])
        self.assertEqual(common_calendar([d], end_ms=3, start_ms=2), [2, 3])
