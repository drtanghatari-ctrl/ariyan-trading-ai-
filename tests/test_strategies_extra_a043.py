"""A043 strategy tests. Synthetic prices, expectations derived by hand."""
import unittest
from decimal import Decimal as D

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.strategies import Signal, Strategy
from ariyan_trading.strategies_extra import (
    BollingerReversion, DonchianBreakout, Ensemble, RsiReversion, TrendFilter, _rsi,
)

I = 60000
L, S, F = Signal.LONG, Signal.SHORT, Signal.FLAT


def bars(closes, start=0):
    out = []
    for i, c in enumerate(closes):
        c = D(str(c))
        out.append(Candle((start + i) * I, c, c, c, c, D(1)))
    return tuple(out)


class Fixed(Strategy):
    name = 'fixed'

    def __init__(self, signal, lookback=1):
        self._signal, self._lookback = signal, lookback

    @property
    def lookback(self):
        return self._lookback

    def target(self, history):
        return self._signal


class TrendFilterTests(unittest.TestCase):
    def test_above_below_and_equal(self):
        up = bars(list(range(100, 110)))
        down = bars(list(range(110, 100, -1)))
        self.assertEqual(TrendFilter(5).target(up), L)
        self.assertEqual(TrendFilter(5).target(down), F)
        self.assertEqual(TrendFilter(5, allow_short=True).target(down), S)
        self.assertEqual(TrendFilter(5, allow_short=True).target(bars([100] * 5)), F)

    def test_uses_only_its_window(self):
        junk = bars([500] * 40)
        window = bars(list(range(100, 110)), start=40)
        self.assertEqual(TrendFilter(5).target(junk + window), TrendFilter(5).target(window))


class DonchianTests(unittest.TestCase):
    strategy = DonchianBreakout(entry_window=5, exit_window=3, allow_short=False, warmup=10)

    def test_breakout_hold_and_exit(self):
        base = [100] * 20
        self.assertEqual(self.strategy.target(bars(base + [101])), L)
        self.assertEqual(self.strategy.target(bars(base + [101, 101, 101])), L)   # holds above the exit channel
        self.assertEqual(self.strategy.target(bars(base + [101, 101, 101, 99])), F)  # below the 3-bar low

    def test_short_only_when_allowed_and_reversal_in_one_bar(self):
        base = [100] * 20
        self.assertEqual(self.strategy.target(bars(base + [99])), F)
        shorting = DonchianBreakout(5, 3, True, 10)
        self.assertEqual(shorting.target(bars(base + [99])), S)
        self.assertEqual(shorting.target(bars(base + [101, 101, 101, 95])), S)    # long exits and flips short

    def test_decision_depends_only_on_the_window(self):
        window = bars([100] * 20 + [101], start=30)
        self.assertEqual(self.strategy.lookback, 16)
        self.assertEqual(self.strategy.target(bars([1] * 30) + window), self.strategy.target(window))

    def test_validation(self):
        for kwargs in ({'entry_window': 1}, {'exit_window': 30}, {'allow_short': 1}):
            with self.assertRaises(ValueError):
                DonchianBreakout(**kwargs)


class RsiTests(unittest.TestCase):
    def test_wilder_rsi_hand_values(self):
        values = _rsi([D(x) for x in (10, 11, 10, 12)], 2)
        self.assertEqual(values[:2], [None, None])
        self.assertEqual(values[2], D(50))
        self.assertEqual(values[3].quantize(D('0.0001')), D('83.3333'))
        self.assertEqual(_rsi([D(x) for x in range(1, 8)], 3)[-1], D(100))
        self.assertEqual(_rsi([D(x) for x in range(8, 1, -1)], 3)[-1], D(0))

    def test_buys_the_dip_inside_an_uptrend_and_exits_on_the_bounce(self):
        strategy = RsiReversion(rsi_period=2, oversold=10, exit_window=3, trend_window=20, warmup=5)
        rise = [100 + i for i in range(25)]                  # 100 .. 124, steady gains
        self.assertEqual(strategy.target(bars(rise)), F)
        self.assertEqual(strategy.target(bars(rise + [123, 122, 121])), F)      # RSI 12.5: not yet < 10
        self.assertEqual(strategy.target(bars(rise + [123, 122, 121, 120])), L)  # RSI 6.25 and above the trend
        self.assertEqual(strategy.target(bars(rise + [123, 122, 121, 120, 130])), F)  # bounce above exit average

    def test_no_long_when_below_the_trend(self):
        strategy = RsiReversion(2, 10, 3, 20, False, 5)
        fall = [200 - i * 2 for i in range(30)]
        self.assertEqual(strategy.target(bars(fall)), F)
        # a small bounce inside the downtrend: RSI(2) reaches 93.9 while the close stays below the average
        self.assertEqual(RsiReversion(2, 10, 3, 20, True, 5).target(bars(fall + [143, 144, 145, 146, 147])), S)


class BollingerTests(unittest.TestCase):
    def test_fade_the_extreme_then_exit_at_the_mean(self):
        strategy = BollingerReversion(window=20, k='2', warmup=5)
        calm = [100, 101] * 13
        self.assertEqual(strategy.target(bars(calm)), F)
        self.assertEqual(strategy.target(bars(calm + [95])), L)
        self.assertEqual(strategy.target(bars(calm + [95, 100.5])), F)
        self.assertEqual(strategy.target(bars(calm + [106])), F)
        self.assertEqual(BollingerReversion(20, '2', True, 5).target(bars(calm + [106])), S)

    def test_flat_prices_never_trigger(self):
        self.assertEqual(BollingerReversion(window=20).target(bars([100] * 80)), F)

    def test_validation(self):
        for kwargs in ({'k': 0}, {'k': 11}, {'window': 1}):
            with self.assertRaises(ValueError):
                BollingerReversion(**kwargs)


class EnsembleTests(unittest.TestCase):
    def test_majority_and_unanimous(self):
        h = bars([1, 2, 3])
        votes = lambda *s: (Fixed(s[0]), Fixed(s[1]), Fixed(s[2]))
        self.assertEqual(Ensemble(votes(L, L, S)).target(h), L)
        self.assertEqual(Ensemble(votes(L, L, S), 'unanimous').target(h), F)
        self.assertEqual(Ensemble(votes(L, L, L), 'unanimous').target(h), L)
        self.assertEqual(Ensemble(votes(S, S, F)).target(h), S)
        self.assertEqual(Ensemble(votes(L, S, F)).target(h), F)

    def test_lookback_and_description_and_validation(self):
        ensemble = Ensemble((Fixed(L, 3), Fixed(S, 7)), 'unanimous')
        self.assertEqual(ensemble.lookback, 7)
        self.assertEqual(ensemble.describe()['params']['rule'], 'unanimous')
        for bad in ((), (Fixed(L),), (Fixed(L), 'x')):
            with self.assertRaises(ValueError):
                Ensemble(bad)
        with self.assertRaises(ValueError):
            Ensemble((Fixed(L), Fixed(S)), 'plurality')


class BacktestSmokeTests(unittest.TestCase):
    def test_new_strategies_run_through_the_backtester(self):
        spec = MarginInstrumentSpec(
            identity=InstrumentIdentity('SYNTHETIC-BROKER', 'X-001'), display_symbol='SYNTH',
            asset_class=A.INDEX, product=P.CFD, base_label='SYNTHETIC index', quote_currency='USD',
            contract_size='1000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
            price_step='0.01', pip_size='0.01', initial_margin_rate='0.1', maintenance_margin_rate='0.05',
            allows_short=True, financing_reference='SYNTHETIC-SWAP-V1', commission_reference='SYNTHETIC-COMMISSION-V1',
            calendar_reference='SYNTHETIC-SESSIONS-V1', timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
            effective_from_ms=0, effective_until_ms=None, source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)
        closes = [100 + (i % 40) - (i % 7) * 2 + i // 10 for i in range(400)]
        candles = bars(closes)
        dataset = CandleDataset(candles, 'SYNTH', I, 'S', 401 * I, 'd' * 64, 'canonical', 'ms')
        for strategy in (TrendFilter(20, True), DonchianBreakout(10, 5, True, 20),
                         RsiReversion(2, 10, 3, 30, True, 10), BollingerReversion(20, '2', True, 10),
                         Ensemble((TrendFilter(20, True), DonchianBreakout(10, 5, True, 20),
                                   BollingerReversion(20, '2', True, 10)))):
            result = run_backtest(dataset, spec, strategy, BacktestConfig(margin_fraction='0.2'))
            self.assertIn('final_equity', result.metrics, strategy.name)


if __name__ == '__main__':
    unittest.main()
