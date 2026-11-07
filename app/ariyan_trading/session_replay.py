"""A017 bounded offline session replay with a fixed SMA test signal; no authority."""
import hashlib
import json
from bisect import bisect_right
from collections import deque
from dataclasses import dataclass, fields, replace
from decimal import Decimal as D, localcontext

from .cash_trade_math import (
    CONTEXT, PRICE_CONVENTION, quote_cash_trade, simulate_cash_trade,
    _round, _number, _text, _grid, _cost,
)
from .session_data import SessionCandleSeries
from .sessions import CoverageKind, IntervalStatus

MAX_AMOUNT = D('1000000000')
MAX_REPLAY_SLOTS = 10000
MAX_TRADES = 1000


@dataclass(frozen=True)
class SessionReplayConfig:
    opening_cash: str
    cash_currency: str
    cash_step: str
    fee_bps: str
    slippage_bps: str
    price_convention: str
    max_buy_fraction: str = '0.10'
    max_position_fraction: str = '0.25'
    max_close_drawdown_pct: str = '10'
    short_window: int = 3
    long_window: int = 5
    max_trades: int = MAX_TRADES

    def __post_init__(self):
        with localcontext(CONTEXT):
            cash = _number(self.opening_cash); step = _number(self.cash_step)
            if not 0 < cash <= MAX_AMOUNT or step <= 0 or not _grid(cash,step):
                raise ValueError('Positive bounded opening cash must fit explicit cash grid')
            _cost(self.fee_bps); _cost(self.slippage_bps)
            for name in ('max_buy_fraction','max_position_fraction'):
                if not 0 < _number(getattr(self,name)) <= 1:
                    raise ValueError('Entry/exposure fractions must be in (0,1]')
            if not 0 < _number(self.max_close_drawdown_pct) <= 100:
                raise ValueError('Close drawdown halt threshold must be in (0,100] percent')
        if type(self.cash_currency) is not str or not self.cash_currency:
            raise ValueError('Explicit cash currency required')
        if type(self.price_convention) is not str or self.price_convention != PRICE_CONVENTION:
            raise ValueError('Explicit cash price convention required')
        if (type(self.short_window) is not int or type(self.long_window) is not int
                or not 1 <= self.short_window < self.long_window <= 1000):
            raise ValueError('Require 1 <= short_window < long_window <= 1000')
        if type(self.max_trades) is not int or not 1 <= self.max_trades <= MAX_TRADES:
            raise ValueError('Bounded positive trade-record limit required')


def _encoded(record):
    return json.dumps(record,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def _options(config):
    return {name:getattr(config,name) for name in
            ('cash_currency','cash_step','fee_bps','slippage_bps','price_convention')}


def _mark(cash,units,price):
    equity = cash+units*price
    if not 0 <= cash <= MAX_AMOUNT or not 0 <= units <= MAX_AMOUNT or not 0 < equity <= MAX_AMOUNT:
        raise ValueError('Replay balance/valuation exceeds supported positive numeric range')
    return equity


def _buy_quantity(spec,config,cash,units,reference):
    equity = _mark(cash,units,reference)
    cap = _number(config.max_position_fraction)
    if units*reference > cap*equity:
        return None
    if spec.minimum_quantity > MAX_AMOUNT-units:
        return None
    # One full quote obtains the tick-rounded adverse price; binary tests use
    # the same A016 exact step-rounding primitive without repeatedly hashing metadata.
    probe = quote_cash_trade(spec,'BUY',spec.minimum_quantity,reference,**_options(config))
    fill = D(probe['modeled_fill_price']); cash_step = _number(config.cash_step)
    fee_rate = _number(config.fee_bps)/D(10000)
    budget = min(cash,equity*_number(config.max_buy_fraction))
    available = MAX_AMOUNT-units
    an,ad = available.as_integer_ratio(); sn,sd = spec.quantity_step.as_integer_ratio()
    lo,hi = 0,(an*sd)//(ad*sn)
    while lo < hi:
        middle = (lo+hi+1)//2
        quantity = spec.quantity_step*middle
        notional = _round(quantity*fill,cash_step,up=True)
        outlay = notional+_round(notional*fee_rate,cash_step,up=True)
        exposure = (units+quantity)*reference
        if outlay <= budget and exposure <= cap*(cash-outlay+exposure):
            lo = middle
        else:
            hi = middle-1
    quantity = spec.quantity_step*lo
    return quantity if quantity >= spec.minimum_quantity else None


def run_session_replay(series, config):
    """Strict-completeness, same-window next-open test replay; no optimization.

    Preflight rejects missing/unknown/boundary/off-session input. This conditions
    the evaluation on declared complete sessions and does not model outages.
    """
    if type(series) is not SessionCandleSeries or type(config) is not SessionReplayConfig:
        raise ValueError('SessionCandleSeries and SessionReplayConfig required')
    config = replace(config)
    intake = series.to_report(); assessment = intake['session_assessment']
    counts = assessment['grid_slot_counts']
    if (series.schedule.coverage_kind is not CoverageKind.EXHAUSTIVE
            or counts[IntervalStatus.UNKNOWN_UNLISTED.value]
            or counts[IntervalStatus.UNKNOWN_OUTSIDE_COVERAGE.value]
            or counts[IntervalStatus.CROSSES_BOUNDARY.value]
            or assessment['missing_session_opens']
            or assessment['observations_outside_full_declared_sessions']):
        raise ValueError('Replay requires complete full-session bars and exhaustive covered schedule/grid')
    if not series.candles or sum(counts.values()) > MAX_REPLAY_SLOTS:
        raise ValueError('Replay requires nonempty input and at most 10000 total grid slots')
    if any(max(b.open,b.high,b.low,b.close)>MAX_AMOUNT for b in series.candles):
        raise ValueError('Replay price exceeds supported bound')
    with localcontext(CONTEXT):
        # Validate product/currency/cost convention even if warmup admits no trade.
        quote_cash_trade(series.spec,'BUY',series.spec.minimum_quantity,series.candles[0].open,**_options(config))
        return _run(series,config,intake)


def _run(series,config,intake):
    cash = _number(config.opening_cash); initial = cash; units = D(0)
    peak = cash; max_dd = D(0); fees = D(0); slip_cost = D(0)
    halted = False; halt_at = None; previous = None; previous_window = None
    long_history = deque(maxlen=config.long_window); short_history = deque(maxlen=config.short_window)
    long_sum = D(0); short_sum = D(0); pending = 'WARMUP'; signal_at = None
    windows = series.schedule.windows; opens = tuple(w.open_ms for w in windows)
    trades = []; curve = []; decisions = []; resets = 0
    for bar in series.candles:
        window = bisect_right(opens,bar.timestamp_ms)-1
        same_window = previous is not None and window == previous_window
        if not same_window:
            long_history.clear(); short_history.clear(); long_sum=D(0); short_sum=D(0)
            pending='WARMUP'; signal_at=None; resets+=1
        open_equity = _mark(cash,units,bar.open)
        cap_exceeded = units*bar.open > _number(config.max_position_fraction)*open_equity
        action = 'SELL' if halted and units>0 else pending
        action_at = halt_at if halted and units>0 else signal_at
        outcome = 'SESSION_START_NO_FILL' if not same_window else 'HOLD_OR_WARMUP'
        execution_error = None
        if same_window and action in ('BUY','SELL'):
            if previous.timestamp_ms+series.interval_ms != bar.timestamp_ms:
                raise ValueError('Unexpected native-time discontinuity inside session')
            if previous.volume == 0:
                outcome = 'SKIP_PREVIOUS_ZERO_VOLUME'
            elif action == 'BUY' and halted:
                outcome = 'SKIP_LATCHED_DRAWDOWN_HALT'
            elif action == 'BUY':
                quantity = _buy_quantity(series.spec,config,cash,units,bar.open)
                outcome = 'SKIP_BUY_CASH_EXPOSURE_OR_MINIMUM' if quantity is None else 'READY'
            else:
                quantity = units if units >= series.spec.minimum_quantity else None
                outcome = 'SKIP_NO_POSITION_OR_MINIMUM' if quantity is None else 'READY'
            if outcome == 'READY':
                if len(trades) >= config.max_trades:
                    raise ValueError('Trade-record resource limit reached; no partial replay returned')
                try:
                    result = simulate_cash_trade(series.spec,action,_text(quantity),_text(bar.open),
                        opening_cash=_text(cash),opening_units=_text(units),**_options(config))
                except ValueError as exc:
                    # Retain failed cash-model execution and unliquidated inventory;
                    # never pretend a risk-triggered exit necessarily filled.
                    outcome='SKIP_CASH_MODEL_UNEXECUTABLE'; execution_error=str(exc)
                else:
                    quote=result['quote']; cash=D(result['cash_after']); units=D(result['units_after'])
                    fees+=D(quote['fee']); slip_cost+=D(quote['modeled_slippage_cost']); outcome='FILLED'
                    trades.append({'side':action,'signal_available_at_ms':action_at,
                        'fill_timestamp_ms':bar.timestamp_ms,'session_window_index':window,
                        'cash_after':_text(cash),'units_after':_text(units),
                        'quote':{k:v for k,v in quote.items() if k not in ('instrument','limitations')}})
        equity = _mark(cash,units,bar.close)
        peak=max(peak,equity); drawdown=(peak-equity)/peak*100; max_dd=max(max_dd,drawdown)
        if not halted and drawdown >= _number(config.max_close_drawdown_pct):
            halted=True; halt_at=bar.timestamp_ms+series.interval_ms
        curve.append({'close_timestamp_ms':bar.timestamp_ms+series.interval_ms,
            'cash':_text(cash),'units':_text(units),'marked_equity':_text(equity),
            'close_drawdown_pct':_text(drawdown),'drawdown_halted':halted})
        if len(long_history)==config.long_window:long_sum-=long_history[0]
        if len(short_history)==config.short_window:short_sum-=short_history[0]
        long_history.append(bar.close); short_history.append(bar.close)
        long_sum+=bar.close; short_sum+=bar.close
        if len(long_history)<config.long_window:
            next_signal='WARMUP'
        else:
            difference=short_sum*config.long_window-long_sum*config.short_window
            next_signal='BUY' if difference>0 else 'SELL' if difference<0 else 'HOLD'
        if halted:next_signal='SELL' if units>0 else 'HALTED_NO_BUYS'
        decisions.append({'bar_open_ms':bar.timestamp_ms,'session_window_index':window,
            'execution_signal':action,'signal_available_at_ms':action_at,'execution_outcome':outcome,
            'execution_error':execution_error,'position_cap_exceeded_at_open':cap_exceeded,
            'signal_at_close':next_signal})
        pending=next_signal; signal_at=bar.timestamp_ms+series.interval_ms
        previous=bar; previous_window=window
    final = _mark(cash,units,series.candles[-1].close)
    return {'version':'ARIYAN-A017-SESSION-REPLAY-V1','mode':'OFFLINE_TEST_REPLAY_NO_AUTHORITY',
        'strategy':'SMA_LEVEL_TEST_STRATEGY_NOT_VALIDATED','intake':intake,
        'config':{f.name:(_text(_number(getattr(config,f.name))) if f.name not in
            ('cash_currency','price_convention','short_window','long_window','max_trades')
            else getattr(config,f.name)) for f in fields(config)},
        'summary':{'opening_cash':_text(initial),'final_cash':_text(cash),'final_units':_text(units),
            'final_marked_equity':_text(final),'net_marked_pnl':_text(final-initial),
            'return_pct':_text((final/initial-1)*100),'max_observed_close_drawdown_pct':_text(max_dd),
            'total_fees':_text(fees),'modeled_slippage_cost':_text(slip_cost),'filled_orders':len(trades),
            'session_warmup_resets':resets,'drawdown_halted':halted,'halt_available_at_ms':halt_at,
            'unexecuted_final_signal':pending,'last_mark_available_at_ms':previous.timestamp_ms+series.interval_ms,
            'last_mark_precedes_requested_end':previous.timestamp_ms+series.interval_ms<series.end_exclusive_ms,
            'unexecutable_cash_model_attempts':sum(d['execution_error'] is not None for d in decisions)},
        'trades':trades,'equity_curve':curve,'decisions':decisions,
        'ledger_posted':False,'strategy_promoted':False,'production_risk_approval_established':False,
        'live_authorized':False,
        'limitations':[
            'Caller schedule/instrument/source declarations remain unverified; no production venue calendar.',
            'Strict-completeness preflight conditions results on available sessions; outages are not simulated.',
            'Only same-window adjacent next-open fills; signals/warmup reset at every listed window.',
            'Holdings/cash carry across closures; no automatic liquidation, corporate actions or dividends.',
            'Prior positive volume does not prove next-open fillability; current volume is not consulted for fills.',
            'Entry/exposure caps are checked at open; price gaps/moves can exceed them afterward.',
            'Drawdown uses observed closes only; the latched halt is not a guaranteed loss limit or exit fill.',
            'Risk exits wait for a prior same-window bar with positive volume, including after closures.',
            'Terminal holdings remain marked at the last observed close without exit costs; marks can be stale.',
            'A016 is conservative synthetic cash arithmetic, not venue execution or portfolio risk approval.',
            'No optimization, profitability, statistical adequacy, shared portfolio or capital authority.']}
