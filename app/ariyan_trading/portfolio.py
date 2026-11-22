"""A048 multi-instrument daily portfolio simulation. Offline, deterministic, research only: no orders, no broker.

A returns-based simulator (floats). Decisions use information up to a bar's CLOSE; fills happen at the next
OPEN; positions earn open-to-open returns. Sizing targets equal volatility per instrument inside a portfolio
volatility target, with a gross-exposure cap, a no-trade buffer, one-way trading costs, daily financing, and a
drawdown control that tapers exposure and then halts. Protocol: docs/engineering/A048_PORTFOLIO_PROTOCOL.md.

Causality is tested: changing any bar after day k cannot change anything decided or earned up to day k.
"""
import math
from dataclasses import dataclass
from types import SimpleNamespace

DAY_MS = 86_400_000


@dataclass(frozen=True)
class Instrument:
    symbol: str
    cost_one_way: float          # share of notional traded
    financing_per_day: float     # share of gross notional per calendar day, both directions
    inverse: bool = False        # price is quote-currency per account-currency unit (USDJPY): USD return = 1 - P0/P1
    financing_long: float = None   # A050: directional financing, cost per calendar day (negative = credit);
    financing_short: float = None  # None means financing_per_day applies to that direction


@dataclass(frozen=True)
class PortfolioConfig:
    opening_equity: float = 10_000.0
    target_vol: float = 0.10
    vol_window: int = 60
    periods_per_year: int = 252
    buffer: float = 0.25
    max_gross: float = 3.0
    cost_mult: float = 1.0
    fin_mult: float = 1.0
    brake_start: float = 0.06
    dd_limit: float = 0.10
    halt_bars: int = 21
    warmup: int = 252

    def __post_init__(self):
        values = (self.opening_equity, self.target_vol, self.buffer, self.max_gross, self.cost_mult, self.fin_mult)
        if not all(math.isfinite(v) and v >= 0 for v in values) or self.opening_equity <= 0 or self.target_vol <= 0:
            raise ValueError('Invalid portfolio configuration')
        if not 0 <= self.brake_start < self.dd_limit < 1:
            raise ValueError('Require 0 <= brake_start < dd_limit < 1')
        if self.vol_window < 2 or self.halt_bars < 1 or self.warmup < 1 or self.periods_per_year < 1:
            raise ValueError('Invalid window settings')


def common_calendar(datasets, end_ms=None, start_ms=None):
    """Sorted timestamps present in EVERY dataset (optionally from start_ms up to end_ms)."""
    sets = [{c.timestamp_ms for c in d.candles} for d in datasets]
    shared = set.intersection(*sets)
    return sorted(t for t in shared if (end_ms is None or t <= end_ms) and (start_ms is None or t >= start_ms))


def _fin_rate(instrument, position):
    rate = instrument.financing_long if position > 0 else instrument.financing_short
    return instrument.financing_per_day if rate is None else rate


def aligned(dataset, calendar):
    index = {c.timestamp_ms: c for c in dataset.candles}
    return [float(index[t].open) for t in calendar], [float(index[t].close) for t in calendar]


def _sign(x):
    return (x > 0) - (x < 0)


def _momentum(closes, k, lookback):
    return _sign(closes[k] / closes[k - lookback] - 1)


def signal(name, closes, k):
    """Signal in [-1, 1] using closes[0..k] only."""
    if name == 'long':
        return 1.0
    if name == 'mom252':
        return float(_momentum(closes, k, 252))
    if name == 'sma200':
        window = closes[k - 199:k + 1]
        return float(_sign(closes[k] - sum(window) / 200))
    if name == 'mom_ens':
        return sum(_momentum(closes, k, n) for n in (63, 126, 252)) / 3
    raise ValueError('Unknown signal %r' % name)


def _daily_vol(closes, k, window):
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(k - window + 1, k + 1)]
    mean = sum(rets) / window
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (window - 1))


def _ret(inst, p0, p1):
    return 1 - p0 / p1 if inst.inverse else p1 / p0 - 1


def simulate(series, instruments, calendar, signal_name, config=PortfolioConfig()):
    """series: {symbol: (opens, closes)} on `calendar` (timestamps). Returns SimpleNamespace result."""
    bars = len(calendar)
    if bars < config.warmup + 3:
        raise ValueError('Calendar too short for the warm-up')
    names = [i.symbol for i in instruments]
    by = {i.symbol: i for i in instruments}
    n = len(names)
    sqrt_p = math.sqrt(config.periods_per_year)
    pos = {s: 0.0 for s in names}
    equity, peak = config.opening_equity, config.opening_equity
    start = config.warmup
    curve = [(calendar[start], equity)]
    pnl = {s: 0.0 for s in names}
    costs = fin_paid = 0.0
    changes = {s: 0 for s in names}
    halts, halted_until, halted_days = 0, -1, 0
    exposure = {s: 0.0 for s in names}
    for k in range(start, bars - 1):
        gap_days = (calendar[k + 1] - calendar[k]) / DAY_MS
        for s in names:
            exposure[s] += abs(pos[s])
        # earn open(k) -> open(k+1) with the position executed at open(k)
        gain = 0.0
        for s in names:
            o, c = series[s]
            move = pos[s] * equity * _ret(by[s], o[k], o[k + 1])
            fin = abs(pos[s]) * equity * _fin_rate(by[s], pos[s]) * config.fin_mult * gap_days
            pnl[s] += move - fin
            fin_paid += fin
            gain += move - fin
        marked = equity  # equity marked at close k, for the drawdown control (no look-ahead)
        for s in names:
            o, c = series[s]
            marked += pos[s] * equity * _ret(by[s], o[k], c[k])
        equity_next = equity + gain
        peak = max(peak, marked)
        dd = 1 - marked / peak
        if k < halted_until:
            halted = True                                   # still flat after a halt
        elif k == halted_until:
            halted, peak, dd = False, marked, 0.0           # review period over: restart, peak reset
        elif dd >= config.dd_limit:
            halted, halts, halted_until = True, halts + 1, k + config.halt_bars
        else:
            halted = False
        target = {s: 0.0 for s in names}
        scale = 0.0 if halted else (1.0 if dd <= config.brake_start else
                                    (config.dd_limit - dd) / (config.dd_limit - config.brake_start))
        full = {}
        if not halted:
            raw = {}
            for s in names:
                closes = series[s][1]
                sigma = _daily_vol(closes, k, config.vol_window)
                full[s] = (config.target_vol / sqrt_p / n) / sigma if sigma > 0 else 0.0
                raw[s] = signal(signal_name, closes, k) * full[s]
            gross = sum(abs(v) for v in raw.values())
            cap = min(1.0, config.max_gross / gross) if gross > 0 else 1.0      # cap first, brake second
            full = {s: v * cap for s, v in full.items()}
            target = {s: raw[s] * cap * scale for s in names}
        else:
            halted_days += 1
        new = dict(pos)
        for s in names:
            if halted:
                new[s] = 0.0
            elif abs(target[s] - pos[s]) > config.buffer * full.get(s, 0.0) or (target[s] == 0.0 and pos[s] != 0.0):
                new[s] = target[s]
        cost = 0.0
        for s in names:
            delta = abs(new[s] - pos[s])
            if delta > 0:
                changes[s] += 1
            paid = delta * equity_next * by[s].cost_one_way * config.cost_mult
            pnl[s] -= paid
            cost += paid
        costs += cost
        equity = equity_next - cost
        pos = new
        curve.append((calendar[k + 1], equity))
    return SimpleNamespace(equity_curve=tuple(curve), trades=(), pnl_by_instrument=pnl, costs_paid=costs,
                           financing_paid=fin_paid, position_changes=sum(changes.values()),
                           changes_by_instrument=changes, halts=halts, halted_bars=halted_days,
                           average_abs_weight={s: exposure[s] / (bars - 1 - start) for s in names},
                           final_equity=equity, signal=signal_name, config=config)
