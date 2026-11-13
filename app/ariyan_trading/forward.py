"""A042 forward PAPER trading on real MT5 candles and quotes. No order is ever sent to MT5.

The MT5 terminal is used read-only (closed candles, quotes, contract terms). Decisions go through
the same SignalExecutor -> GuardedBroker pipeline as a real run, but the broker underneath is the
A039 PaperBroker, a simulated account kept in memory. Each newly closed candle and every action is
appended to a JSON-lines log, so the run can be reviewed afterwards.

Limits (stated, not hidden):
- Paper account is in USD and only USD-quoted six-letter forex pairs (EURUSD, GBPUSD, ...) are supported.
- Fills use the quote at the moment the loop notices the closed candle, spread included. Swap/financing
  and commission are not modelled. Execution on a real account would differ.
- Paper state lives in memory: a restart starts a new run with a fresh account.
- Candle times are broker server time (see MT5DemoBroker.closed_candles).
"""
import json
import time as _time
from decimal import Decimal

from .execution import GuardedBroker, PaperBroker, RiskLimits, SignalExecutor
from .instruments import InstrumentIdentity
from .margin_instruments import MarginAssetClass, MarginInstrumentSpec, MarginProduct
from .mt5_adapter import MT5Error


def paper_spec_from_terms(symbol, terms, margin_rate, now_ms):
    """Build the paper instrument from what the terminal reports for the symbol."""
    if len(symbol) != 6 or not symbol.isalpha() or not symbol.isupper() or symbol[3:] != 'USD':
        raise ValueError('Only USD-quoted six-letter forex pairs (e.g. EURUSD) are supported for now')
    point = terms['point']
    pip = point * 10 if terms['digits'] in (3, 5) else point
    rate = Decimal(str(margin_rate))
    return MarginInstrumentSpec(
        identity=InstrumentIdentity('MT5-FORWARD-PAPER', symbol), display_symbol=symbol,
        asset_class=MarginAssetClass.FOREX, product=MarginProduct.FX_MARGIN, base_label=symbol[:3],
        quote_currency='USD', contract_size=terms['contract_size'], lot_step=terms['lot_step'],
        minimum_lot=terms['lot_min'], maximum_lot=terms['lot_max'], price_step=point, pip_size=pip,
        initial_margin_rate=rate, maintenance_margin_rate=rate / 2, allows_short=True,
        financing_reference='PAPER-NO-SWAP-MODEL', commission_reference='PAPER-NO-COMMISSION-MODEL',
        calendar_reference='PAPER-SESSIONS-NOT-MODELLED', corporate_action_reference='NOT_APPLICABLE',
        timezone_label='UTC', effective_from_ms=0, effective_until_ms=None,
        source_label='MT5 symbol_info via forward runner', observed_at_ms=now_ms)


class ForwardPaperRunner:
    def __init__(self, source, strategy, symbol, timeframe, lots, run_id, log_path, *,
                 opening_cash='10000', margin_rate='0.01', stop_distance=None, clock_ms=None):
        self._src, self._symbol, self._tf = source, symbol, timeframe
        source.timeframe_seconds(timeframe)
        self._clock = clock_ms or (lambda: int(_time.time() * 1000))
        spec = paper_spec_from_terms(symbol, source.symbol_terms(symbol), margin_rate, self._clock())
        self.paper = PaperBroker({symbol: spec}, opening_cash, 'USD')
        quote = source.quote(symbol)
        self.paper.set_quote(symbol, quote.bid, quote.ask, quote.time_ms)
        lots = Decimal(str(lots))
        limits = RiskLimits(frozenset({symbol}), lots, 1, lots, Decimal('0.5'), Decimal('0.2'),
                            require_stop_loss=stop_distance is not None)
        self.guard = GuardedBroker(self.paper, limits)
        self._strategy = strategy
        self.executor = SignalExecutor(self.guard, strategy, symbol, lots, run_id,
                                       stop_distance=None if stop_distance is None else Decimal(str(stop_distance)))
        self._fetch = max(strategy.lookback + 5, 50)
        self._log_path, self._last_ms = log_path, None
        self._write({'event': 'START', 'symbol': symbol, 'timeframe': timeframe, 'lots': str(lots),
                     'strategy': strategy.describe(), 'run_id': run_id, 'paper_only': True,
                     'opening_cash_usd': str(opening_cash)})

    def _write(self, record):
        record = dict(record, logged_ms=self._clock())
        with open(self._log_path, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, sort_keys=True) + '\n')

    def step(self):
        """Fetch data once; trade the paper account on each newly closed candle. Returns new records."""
        candles = self._src.closed_candles(self._symbol, self._tf, self._fetch)
        quote = self._src.quote(self._symbol)
        if quote.time_ms >= self.paper.quote(self._symbol).time_ms:
            self.paper.set_quote(self._symbol, quote.bid, quote.ask, quote.time_ms)
        if self._last_ms is None:
            self.executor.warm_up(candles)
            self._last_ms = candles[-1].timestamp_ms
            return []
        records = []
        for candle in candles:
            if candle.timestamp_ms <= self._last_ms:
                continue
            actions = self.executor.on_candle(candle) or ()
            self._last_ms = candle.timestamp_ms
            account = self.paper.account()
            record = {'event': 'CANDLE', 'candle_time_server': candle.timestamp_ms,
                      'open': str(candle.open), 'high': str(candle.high), 'low': str(candle.low),
                      'close': str(candle.close), 'bid': str(quote.bid), 'ask': str(quote.ask),
                      'actions': [{'id': a.client_order_id, 'status': a.status, 'reason': a.reason,
                                   'price': None if a.price is None else str(a.price)} for a in actions],
                      'paper_equity_usd': str(account.equity), 'halted': self.guard.halted}
            self._write(record)
            records.append(record)
        return records

    def run(self, poll_seconds=30, max_steps=None, sleep=_time.sleep, max_errors=5):
        steps = errors = 0
        while max_steps is None or steps < max_steps:
            try:
                self.step()
                errors = 0
            except MT5Error as exc:
                errors += 1
                self._write({'event': 'ERROR', 'error': str(exc), 'consecutive': errors})
                if errors >= max_errors:
                    self._write({'event': 'STOPPED', 'reason': 'TOO_MANY_ERRORS'})
                    raise
            steps += 1
            if max_steps is None or steps < max_steps:
                sleep(poll_seconds)
        self._write({'event': 'STOPPED', 'reason': 'MAX_STEPS'})
