"""A045 performance scorecard and Deflated Sharpe Ratio. Offline; statistics use floats, deterministic seed.

`scorecard(result, periods_per_year)` summarises a BacktestResult: return, volatility, downside
volatility, drawdown depth and duration, Sharpe, Sortino, Calmar, expected shortfall, per-year returns,
trade statistics (win rate only next to average win/loss and payoff), and block-bootstrap confidence
intervals. Bootstrapping cannot repair bad data or regime change; it only shows sampling noise.

The Deflated Sharpe Ratio follows Bailey & Lopez de Prado (2014): the probability that the true Sharpe is
above zero after allowing for non-normal returns, a short sample and the number of strategies tried.
Sharpe inputs here are PER BAR (not annualised).
"""
import math
import random
from datetime import datetime, timezone
from statistics import NormalDist

_N = NormalDist()
EULER_GAMMA = 0.5772156649015329
FLAT = 1e-12  # volatility below this is float noise, not risk


def _returns(curve):
    values = [float(equity) for _, equity in curve]
    return [b / a - 1 if a > 0 else 0.0 for a, b in zip(values, values[1:])]


def _moments(returns):
    n = len(returns)
    mean = sum(returns) / n
    pop = sum((r - mean) ** 2 for r in returns) / n
    sd_pop = math.sqrt(pop)
    skew = sum((r - mean) ** 3 for r in returns) / n / sd_pop ** 3 if sd_pop > 0 else 0.0
    kurt = sum((r - mean) ** 4 for r in returns) / n / sd_pop ** 4 if sd_pop > 0 else 3.0
    sd = math.sqrt(sum((r - mean) ** 2 for r in returns) / (n - 1)) if n > 1 else 0.0
    return mean, sd, skew, kurt


def _drawdown(curve):
    peak, worst, run, longest, trough_at, trough_peak, recovery = None, 0.0, 0, 0, 0, None, None
    values = [float(e) for _, e in curve]
    for index, value in enumerate(values):
        if peak is None or value >= peak:
            peak, run = value, 0
            continue
        run += 1
        longest = max(longest, run)
        depth = (peak - value) / peak
        if depth > worst:
            worst, trough_at, trough_peak = depth, index, peak
    if worst > 0:
        recovery = next((i - trough_at for i in range(trough_at, len(values)) if values[i] >= trough_peak), None)
    return worst, longest, recovery


def _annualised(returns, periods_per_year):
    growth = 1.0
    for r in returns:
        growth *= 1 + r
    return growth ** (periods_per_year / len(returns)) - 1 if growth > 0 else -1.0


def _percentile(sorted_values, q):
    index = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return sorted_values[index]


def scorecard(result, periods_per_year, bootstrap=1000, block=20, seed=1, confidence=0.9):
    curve = result.equity_curve
    returns = _returns(curve)
    n = len(returns)
    if n < 30:
        raise ValueError('At least 30 bars are needed for a scorecard')
    if type(periods_per_year) is not int or periods_per_year < 1:
        raise ValueError('periods_per_year must be a positive integer')
    root = math.sqrt(periods_per_year)
    mean, sd, skew, kurt = _moments(returns)
    downside = math.sqrt(sum(min(r, 0.0) ** 2 for r in returns) / n)
    depth, duration, recovery = _drawdown(curve)
    sharpe_bar = mean / sd if sd > FLAT else None
    years = n / periods_per_year
    annual = _annualised(returns, periods_per_year) if years >= 1 else None
    ordered = sorted(returns)
    tail = ordered[:max(1, int(n * 0.05))]
    trades = result.trades
    wins = [float(t.net_pnl) for t in trades if t.net_pnl > 0]
    losses = [float(t.net_pnl) for t in trades if t.net_pnl < 0]
    year_start, year_end, previous = {}, {}, float(curve[0][1])
    for ts, equity in curve[1:]:
        year = datetime.fromtimestamp(ts / 1000, timezone.utc).year
        year_start.setdefault(year, previous)
        year_end[year] = previous = float(equity)
    yearly = {str(y): year_end[y] / year_start[y] - 1 for y in sorted(year_end)}
    card = {
        'bars': n, 'years': years,
        'total_return': float(curve[-1][1]) / float(curve[0][1]) - 1,
        'annualised_return': annual,
        'volatility': sd * root, 'downside_volatility': downside * root,
        'max_drawdown': depth, 'max_drawdown_duration_bars': duration, 'max_drawdown_recovery_bars': recovery,
        'sharpe_per_bar': sharpe_bar, 'sharpe_annualised': None if sharpe_bar is None else sharpe_bar * root,
        'sortino_annualised': mean / downside * root if downside > FLAT else None,
        'calmar': annual / depth if annual is not None and depth > 0 else None,
        'expected_shortfall_5pct_per_bar': sum(tail) / len(tail), 'worst_bar': ordered[0],
        'skewness': skew, 'kurtosis': kurt, 'yearly_returns': yearly,
        'trades': len(trades), 'win_rate': len(wins) / len(trades) if trades else None,
        'average_win': sum(wins) / len(wins) if wins else None,
        'average_loss': sum(losses) / len(losses) if losses else None,
        'payoff_ratio': (sum(wins) / len(wins)) / (-sum(losses) / len(losses)) if wins and losses else None,
        'profit_factor': sum(wins) / -sum(losses) if losses else None,
        'expectancy_per_trade': sum(float(t.net_pnl) for t in trades) / len(trades) if trades else None,
    }
    rng = random.Random(seed)
    sharpes, annuals = [], []
    for _ in range(bootstrap):
        sample = []
        while len(sample) < n:
            start = rng.randrange(0, n)
            sample.extend(returns[start:start + block])
        sample = sample[:n]
        m, s, _, _ = _moments(sample)
        if s > FLAT:
            sharpes.append(m / s * root)
        annuals.append(_annualised(sample, periods_per_year))
    low, high = (1 - confidence) / 2, 1 - (1 - confidence) / 2
    sharpes.sort(), annuals.sort()
    card['confidence'] = confidence
    card['sharpe_annualised_ci'] = [_percentile(sharpes, low), _percentile(sharpes, high)] if sharpes else None
    card['annualised_return_ci'] = [_percentile(annuals, low), _percentile(annuals, high)]
    return card


def probabilistic_sharpe(sharpe, n_obs, skew, kurt, benchmark=0.0):
    """P(true per-bar Sharpe > benchmark) given the observed one (Bailey & Lopez de Prado 2012)."""
    if n_obs < 2:
        raise ValueError('n_obs must be at least 2')
    inside = 1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2
    if inside <= 0:
        raise ValueError('Moments are inconsistent with this Sharpe ratio')
    return _N.cdf((sharpe - benchmark) * math.sqrt(n_obs - 1) / math.sqrt(inside))


def expected_max_sharpe(n_trials, trial_sharpe_variance):
    """Expected best per-bar Sharpe among n_trials unskilled strategies (0 for a single trial)."""
    if n_trials < 1 or trial_sharpe_variance < 0:
        raise ValueError('n_trials must be >= 1 and the variance non-negative')
    if n_trials == 1:
        return 0.0
    return math.sqrt(trial_sharpe_variance) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n_trials)
                                               + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n_trials * math.e)))


def deflated_sharpe(sharpe, n_obs, skew, kurt, n_trials, trial_sharpe_variance):
    """Probability the true Sharpe is positive after allowing for the number of strategies tried."""
    return probabilistic_sharpe(sharpe, n_obs, skew, kurt, expected_max_sharpe(n_trials, trial_sharpe_variance))
