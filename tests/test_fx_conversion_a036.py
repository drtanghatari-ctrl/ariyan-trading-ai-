"""Synthetic prices and instruments only; hand-computed expectations."""
import json
import unittest
from dataclasses import replace
from decimal import Decimal as D

from ariyan_trading.backtest import BacktestConfig, run_backtest
from ariyan_trading.fx_conversion import ConversionLeg, build_rates, validate_path
from ariyan_trading.instruments import InstrumentIdentity
from ariyan_trading.margin_instruments import (
    MarginAssetClass as A, MarginInstrumentSpec, MarginProduct as P,
)
from ariyan_trading.market_data import Candle, CandleDataset
from ariyan_trading.strategies import BuyAndHold

INTERVAL = 60000


def spec(**changes):
    terms = dict(
        identity=InstrumentIdentity('SYNTHETIC-BROKER', 'FX-001'), display_symbol='SYNTH',
        asset_class=A.INDEX, product=P.CFD, base_label='SYNTHETIC index', quote_currency='JPY',
        contract_size='1000', lot_step='0.01', minimum_lot='0.01', maximum_lot='100',
        price_step='0.01', pip_size='0.01', initial_margin_rate='0.1',
        maintenance_margin_rate='0.05', allows_short=True, financing_reference='SYNTHETIC-SWAP-V1',
        commission_reference='SYNTHETIC-COMMISSION-V1', calendar_reference='SYNTHETIC-24X7-V1',
        timezone_label='UTC', corporate_action_reference='NOT_APPLICABLE',
        effective_from_ms=0, effective_until_ms=None,
        source_label='SYNTHETIC TEST ONLY', observed_at_ms=1)
    terms.update(changes)
    return MarginInstrumentSpec(**terms)


def dataset(rows, symbol='SYNTH'):
    candles = tuple(Candle(i * INTERVAL, D(o), D(h), D(l), D(c), D(1))
                    for i, (o, h, l, c) in enumerate(rows))
    return CandleDataset(candles, symbol, INTERVAL, 'SYNTHETIC TEST ONLY',
                         len(rows) * INTERVAL, 'b' * 64, 'canonical', 'ms')


UP = [(100, 100, 100, 100), (100, 110, 100, 110), (110, 110, 110, 110)]


def flat(price, n=3):
    return [(price, price, price, price)] * n


CONFIG = dict(margin_fraction='0.5')


class FxConversionA036Tests(unittest.TestCase):
    def test_inverted_leg_jpy_quote_to_usd_account(self):
        leg = ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True)
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(account_currency='USD', **CONFIG), (leg,))
        t, = r.trades
        # 5000 USD / (100 x 1000 x 0.1 x 0.01 = 100 USD per lot) = 50 lots
        self.assertEqual(t.lots, D(50))
        self.assertEqual(t.gross_pnl, D(5000))  # 10 x 50 x 1000 JPY x 0.01
        self.assertEqual((t.fx_open, t.fx_close), (D('0.01'), D('0.01')))
        self.assertEqual(r.metrics['final_equity'], '15000.000000')
        self.assertEqual(r.metrics['account_currency'], 'USD')
        self.assertEqual(r.provenance['quote_currency'], 'JPY')

    def test_direct_leg_gbp_quote_to_usd_account(self):
        leg = ConversionLeg(dataset(flat('1.25'), 'GBPUSD'), 'GBP', 'USD', False)
        r = run_backtest(dataset(UP), spec(quote_currency='GBP'), BuyAndHold(),
                         BacktestConfig(account_currency='USD', **CONFIG), (leg,))
        t, = r.trades
        self.assertEqual(t.lots, D('0.4'))      # 5000 / (100 x 1000 x 0.1 x 1.25)
        self.assertEqual(t.gross_pnl, D(5000))  # 4000 GBP x 1.25
        self.assertEqual(r.metrics['final_equity'], '15000.000000')

    def test_two_leg_chain_jpy_to_usd_to_eur(self):
        legs = (ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True),
                ConversionLeg(dataset(flat('1.25'), 'EURUSD'), 'USD', 'EUR', True))
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(account_currency='EUR', **CONFIG), legs)
        t, = r.trades
        self.assertEqual(t.fx_open, D('0.008'))  # 0.01 x 0.8
        self.assertEqual(t.lots, D('62.5'))      # 5000 / 80 EUR per lot
        self.assertEqual(t.gross_pnl, D(5000))
        self.assertEqual(r.metrics['final_equity'], '15000.000000')

    def test_rate_move_changes_realized_profit(self):
        # USDJPY 100 at entry, 125 at the end: JPY weakens, so JPY profit converts to less USD.
        conv = [(100, 100, 100, 100), (100, 100, 100, 100), (125, 125, 125, 125)]
        leg = ConversionLeg(dataset(conv, 'USDJPY'), 'JPY', 'USD', True)
        r = run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(account_currency='USD', **CONFIG), (leg,))
        t, = r.trades
        self.assertEqual((t.fx_open, t.fx_close), (D('0.01'), D('0.008')))
        self.assertEqual(t.gross_pnl, D(4000))  # 500,000 JPY x 0.008
        self.assertEqual(r.metrics['final_equity'], '14000.000000')

    def test_commission_and_financing_are_account_currency(self):
        leg = ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True)
        r = run_backtest(dataset(UP), spec(), BuyAndHold(), BacktestConfig(
            account_currency='USD', commission_per_lot_per_side='1',
            financing_long_per_lot_per_bar='0.5', **CONFIG), (leg,))
        t, = r.trades
        self.assertEqual((t.lots, t.commission, t.financing), (D(50), D(100), D(50)))
        self.assertEqual(t.net_pnl, D(4850))

    def test_stop_out_converts_losses_at_the_adverse_rate(self):
        main = [(100, 100, 100, 100), (100, 100, 90, 95), (95, 95, 95, 95)]
        calm = run_backtest(dataset(main), spec(), BuyAndHold(),
                            BacktestConfig(account_currency='USD', **CONFIG),
                            (ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True),))
        self.assertEqual(calm.metrics['stop_outs'], 0)
        # Same prices, but USDJPY dips to 50 intrabar: JPY strengthens to 0.02 USD, doubling the loss.
        wild = [(100, 100, 100, 100), (100, 100, 50, 100), (100, 100, 100, 100)]
        r = run_backtest(dataset(main), spec(), BuyAndHold(),
                         BacktestConfig(account_currency='USD', **CONFIG),
                         (ConversionLeg(dataset(wild, 'USDJPY'), 'JPY', 'USD', True),))
        t, = r.trades
        self.assertEqual((t.reason, t.exit_price, t.fx_close), ('STOP_OUT', D(90), D('0.02')))
        self.assertEqual(t.gross_pnl, D(-10000))  # 10 x 50 x 1000 JPY x 0.02
        self.assertEqual(r.metrics['stop_outs'], 1)

    def test_short_gains_use_the_lowest_rate_in_stop_out_tests(self):
        rows = [(100, 100, 100, 100), (100, 100, 100, 100), (100, 100, 100, 100)]
        wild = [(100, 100, 100, 100), (100, 100, 50, 100), (100, 100, 100, 100)]
        from ariyan_trading.strategies import Signal, Strategy

        class Short(Strategy):
            name = 'short'
            lookback = 1

            def target(self, history):
                return Signal.SHORT

        r = run_backtest(dataset(rows), spec(), Short(), BacktestConfig(account_currency='USD', **CONFIG),
                         (ConversionLeg(dataset(wild, 'USDJPY'), 'JPY', 'USD', True),))
        self.assertEqual(r.metrics['stop_outs'], 0)

    def test_path_validation(self):
        usdjpy = dataset(flat(100), 'USDJPY')
        good = ConversionLeg(usdjpy, 'JPY', 'USD', True)
        validate_path((good,), 'JPY', 'USD')
        validate_path((), 'USD', 'USD')
        for legs, quote, account in (((), 'JPY', 'USD'), ((good,), 'USD', 'USD'), ((good,), 'GBP', 'USD'),
                                     ((good,), 'JPY', 'EUR'), ([good], 'JPY', 'USD'), (('x',), 'JPY', 'USD')):
            with self.assertRaises(ValueError):
                validate_path(legs, quote, account)

    def test_run_backtest_rejects_inconsistent_conversion(self):
        data, leg = dataset(UP), ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True)
        with self.assertRaises(ValueError):
            run_backtest(data, spec(), BuyAndHold(), BacktestConfig(account_currency='USD'))
        with self.assertRaises(ValueError):
            run_backtest(data, spec(), BuyAndHold(), BacktestConfig(), (leg,))
        with self.assertRaises(ValueError):
            run_backtest(data, spec(), BuyAndHold(), BacktestConfig(account_currency='EUR'), (leg,))

    def test_missing_conversion_candle_is_rejected(self):
        short_leg = ConversionLeg(dataset(flat(100, 2), 'USDJPY'), 'JPY', 'USD', True)
        with self.assertRaises(ValueError):
            run_backtest(dataset(UP), spec(), BuyAndHold(),
                         BacktestConfig(account_currency='USD', **CONFIG), (short_leg,))

    def test_leg_validation(self):
        data = dataset(flat(100), 'USDJPY')
        for args in ((object(), 'JPY', 'USD', True), (data, 'JPY', 'JPY', True),
                     (data, '', 'USD', True), (data, 'jpy', 'USD', True), (data, 'JPY', 'USD', 1)):
            with self.assertRaises(ValueError):
                ConversionLeg(*args)

    def test_rates_for_inverted_leg_use_opposite_extremes(self):
        leg = ConversionLeg(dataset([(100, 125, 80, 100)] * 2, 'USDJPY'), 'JPY', 'USD', True)
        rates, _ = build_rates((leg,), [0, INTERVAL])
        self.assertEqual((rates.open, rates.close, rates.high, rates.low),
                         (D('0.01'), D('0.01'), D('0.0125'), D('0.008')))

    def test_record_lists_conversion_legs_and_is_deterministic(self):
        leg = ConversionLeg(dataset(flat(100), 'USDJPY'), 'JPY', 'USD', True)
        args = (dataset(UP), spec(), BuyAndHold(), BacktestConfig(account_currency='USD', **CONFIG), (leg,))
        a, b = run_backtest(*args), run_backtest(*args)
        self.assertEqual(json.dumps(a.to_record(include_curve=True)), json.dumps(b.to_record(include_curve=True)))
        self.assertEqual(a.provenance['conversion'][0]['symbol'], 'USDJPY')
        self.assertIn('conversion legs were applied', a.provenance['currency_note'])
        self.assertEqual(a.trades[0].to_record()['fx_open'], '0.010000')

    def test_identity_run_is_unchanged_by_default(self):
        plain = run_backtest(dataset(UP), spec(quote_currency='USD'), BuyAndHold(), BacktestConfig(**CONFIG))
        self.assertEqual(plain.metrics['final_equity'], '15000.000000')
        self.assertEqual(plain.provenance['conversion'], [])


if __name__ == '__main__':
    unittest.main()
