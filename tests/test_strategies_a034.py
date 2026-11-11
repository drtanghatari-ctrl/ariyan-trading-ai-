"""Strategy interface tests on synthetic candles only."""
import unittest
from decimal import Decimal as D

from ariyan_trading.market_data import Candle
from ariyan_trading.strategies import BuyAndHold, Momentum, Signal, SmaCross, Strategy


def candles(closes, start=0, interval=60000):
    out = []
    for i, close in enumerate(closes):
        c = D(close)
        out.append(Candle(start + i * interval, c, c, c, c, D(1)))
    return tuple(out)


class StrategiesA034Tests(unittest.TestCase):
    def test_sma_cross_signals(self):
        s = SmaCross(2, 4)
        self.assertEqual(s.lookback, 4)
        self.assertIs(s.target(candles([1, 2, 3, 4])), Signal.LONG)
        self.assertIs(s.target(candles([4, 3, 2, 1])), Signal.SHORT)
        self.assertIs(s.target(candles([5, 5, 5, 5])), Signal.FLAT)
        self.assertIs(SmaCross(2, 4, allow_short=False).target(candles([4, 3, 2, 1])), Signal.FLAT)

    def test_sma_cross_comparison_is_exact_without_rounding(self):
        # 3-bar fast vs 7-bar slow averages that only differ below any rounding step.
        s = SmaCross(3, 7)
        rising = candles(['1.000000000001'] * 6 + ['1.000000000002'])
        self.assertIs(s.target(rising), Signal.LONG)

    def test_only_the_last_lookback_candles_matter(self):
        s = SmaCross(2, 4)
        base = candles([1, 2, 3, 4])
        longer = candles([900, 800, 1, 2, 3, 4])
        self.assertEqual(s.target(base), s.target(longer))

    def test_momentum(self):
        m = Momentum(3)
        self.assertEqual(m.lookback, 4)
        self.assertIs(m.target(candles([1, 5, 5, 2])), Signal.LONG)
        self.assertIs(m.target(candles([2, 5, 5, 1])), Signal.SHORT)
        self.assertIs(m.target(candles([2, 9, 9, 2])), Signal.FLAT)
        self.assertIs(Momentum(3, allow_short=False).target(candles([2, 5, 5, 1])), Signal.FLAT)

    def test_buy_and_hold(self):
        self.assertIs(BuyAndHold().target(candles([7])), Signal.LONG)
        self.assertEqual(BuyAndHold().lookback, 1)

    def test_invalid_parameters(self):
        for build in (lambda: SmaCross(5, 5), lambda: SmaCross(0, 5), lambda: SmaCross(3, 2),
                      lambda: SmaCross(2, 10_001), lambda: SmaCross(2, 5, allow_short=1),
                      lambda: SmaCross('2', 5), lambda: SmaCross(True, 5),
                      lambda: Momentum(0), lambda: Momentum(10_000), lambda: Momentum(3, 'yes')):
            with self.assertRaises(ValueError):
                build()

    def test_history_validation(self):
        s = SmaCross(2, 4)
        for bad in (candles([1, 2, 3]), list(candles([1, 2, 3, 4])), [1, 2, 3, 4],
                    (1, 2, 3, 4), None):
            with self.assertRaises(ValueError):
                s.target(bad)

    def test_describe_records_name_and_parameters(self):
        self.assertEqual(SmaCross(2, 4).describe(),
                         {'name': 'sma_cross',
                          'params': {'short_window': '2', 'long_window': '4', 'allow_short': 'True'}})
        self.assertEqual(BuyAndHold().describe(), {'name': 'buy_and_hold', 'params': {}})

    def test_strategy_is_abstract_and_immutable(self):
        with self.assertRaises(TypeError):
            Strategy()
        with self.assertRaises(Exception):
            SmaCross(2, 4).short_window = 3


if __name__ == '__main__':
    unittest.main()
