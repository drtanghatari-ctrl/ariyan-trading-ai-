# A017 — bounded offline session replay

Based on A016 checkpoint `650eb37`. Adds `session_replay.py`, twenty-one tests
and this document. Connects A015 intake and A016 cash arithmetic without changing
the existing loader, replay, ledger, authorization, demo or CI implementation.
No new real-market performance experiment, parameter search or promotion occurs.

## API and strict input policy

`run_session_replay(series, config)` requires exact A015 `SessionCandleSeries`
and `SessionReplayConfig` types. Intake is revalidated before any simulated
trade. The schedule must be declared exhaustive and cover the whole queried
grid. Missing expected session bars, unknown coverage, boundary-crossing grid
intervals and observations outside full sessions reject the entire run.

This intentionally bounded version does not model source outages or ambiguous
closing bars. It never fills, compresses or repairs gaps, or returns an optimistic
partial prefix. A query needs at least one candle and at most 10,000 total grid
slots, including closures. Specifying a finer grid or a different query is an
explicit caller decision, not an automatic workaround. Input and observed
marked values have a 1,000,000,000 computational bound, not a capital permission.

Preflight sees full input availability. Results are conditioned on complete,
caller-declared sessions, not evidence that such data were available in real
time. Selecting complete windows after inspecting performance can bias findings.
Schedules, venue terms, corporate-action references and mappings remain unsigned
and unverified. No production calendar/venue adapter is installed.

A016 product/currency/price conventions are validated even if warmup produces
no trades. Only its unlevered spot/share/fund-share cash model is supported;
futures and mixed-currency settlement remain rejected. Positive candle prices,
explicit grids, one instrument definition for the query and all A015 restrictions
still apply. There is no automatic conversion to A007 or shared portfolio.

## Fixed test signal and session policy

The only built-in signal is the existing SMA-level TEST idea: compare the short
and long completed-close means by cross multiplication; BUY above, SELL below,
HOLD on equality. Default windows are 3/5, with no search or training. The signal
is not asserted to have an edge; earlier SMA research was unpromoted. Tests use
synthetic fixtures and parameters for mechanical checks, not economic selection.

Each listed session window, including adjacent windows, resets signal state,
MA history and warmup. Signals fill only at the exact next open in the SAME
window, after their close-derived information becomes available. No ordinary
signal is carried across a closure or window boundary. Cash and holdings DO
carry, with no forced session-end liquidation or corporate-action adjustment.
Every run starts with configured cash and zero holdings; accounts/risk state
do not persist between runs.

The first bar in each window cannot fill. A fill also requires positive volume
on the prior same-window bar. Current-bar volume, high, low and close never
determine its open fill. Prior positive volume is only a simplifying assumption,
not proof of available depth or next-open fillability. Decisions are recomputed
at every observed close; ordinary unfilled signals are not queued as broker orders.

## Sizing and cash arithmetic

All modeled trades use A016 adverse tick rounding, conservative cash rounding,
fee rounding and explicit currency/cash-step convention. No legacy A007 rounding
is substituted. Buys select the largest declared quantity-step multiple that
fits both:

* fee-inclusive outlay <= cash and pretrade open marked equity × max_buy_fraction;
* post-buy exposure at reference open <= max_position_fraction × post-cost open
  marked equity.

Opening cash must be positive/on its cash grid. Fractions are in (0,1]. Defaults
are 0.10 per-buy outlay and 0.25 exposure; these are test limits, not evidence of
suitability or human risk approval. Zero/undersized trades are skipped. Existing
open exposure already over the cap blocks new buys. Price gaps and subsequent
price movement can exceed the exposure cap: it is an entry constraint, not a
guaranteed continuous risk ceiling. Open cap breaches are retained in decisions.

Sells attempt the full modeled position. There is no leverage, shorting,
partial-fill model or extra subtraction of slippage. Unexecutable A016 balance
attempts are retained as explicit errors/skips, with no fabricated fill, balance
change or liquidation. Minimum size, dust, zero rounded proceeds and fee-consumed
proceeds can prevent exits. Such runs must not be described as clean successful
execution merely because the engine returned a report.

## Latched observed-close drawdown halt

The peak begins at opening cash. Drawdown uses observed CLOSE marks only, not
intrabar lows or unobserved prices during closures. At or above the configured
threshold (default 10 percent), the halt latches for the rest of this run. No
more buys occur. Existing holdings trigger repeated SELL attempts at eligible
opens; the exit intent survives session resets, unlike ordinary SMA signals.

After a closure, a risk exit still waits for a previous same-window bar with
positive volume. It therefore cannot fill at the first reopening bar. Zero prior
volume or cash-model failure can leave the position open. The threshold is NOT
a guaranteed loss limit, emergency flattening mechanism or production risk
controller. Overnight price gaps can create a larger loss before a modeled exit.
The halt never resets automatically within the replay.

## Output and limits

The report retains the full intake, normalized config, trades, observed-close
equity curve, decisions, fees/slippage, open exposure breaches, halt state/time
and cash-model errors. Each compact trade quote omits duplicate instrument text
and limitations but keeps the full A016 quote fingerprint; original quote inputs
and the root instrument/config allow reconstruction. Hashes are unsigned content
identifiers, not venue acknowledgements or authority tokens.

Terminal holdings remain marked at the last observed close, without forced
liquidation or exit costs. The report records that mark's availability time and
whether it precedes the requested end. Closed-slot prices/equity are never
invented or carried into a fictitious curve. Returns are descriptive marked
account arithmetic, not realized liquidation returns or statistical evidence.

The trade-record limit is explicitly configurable up to 1,000. Reaching it raises
without returning a partial report; it is a resource bound, not a performance
grade. Derived cash/units/open and close valuations outside the computational
range reject the run. No report-file writer, persistent account, capital
allocation controller or cross-run risk state is provided.

The nested A015 intake's replay-availability flag is unchanged: it describes
that intake component's contract. A017 adds this distinct offline consumer; it
does not upgrade that historical record's authenticity or enforcement flags.
Root flags explicitly deny ledger posting, strategy promotion, production risk
approval and live authority. The function contacts no service and writes nothing.

## Example

```
from ariyan_trading.cash_trade_math import PRICE_CONVENTION
from ariyan_trading.session_replay import SessionReplayConfig, run_session_replay

# series is explicitly loaded and independently sourced/declared through A015.
config = SessionReplayConfig(
    opening_cash="10000", cash_currency="USD", cash_step="0.01",
    fee_bps="10", slippage_bps="5", price_convention=PRICE_CONVENTION,
)
report = run_session_replay(series, config)
```

No minimum sample adequacy, significance test or passing return threshold is
assigned. Corporate actions, dividends, settlements, halts, live latency/depth,
dynamic venue filters, broader capital survival and authenticated human authority
still need separate validated implementations. A017 does not establish
profitability, multi-market trading readiness or a completed V1.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a017.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-one synthetic tests cover postings/final marks, reconstructed A016 quotes,
fee-inclusive budget and maximal sizing, post-cost exposure, fractional grids,
supported profiles, same-window timing, session resets/carry, future/current-bar
isolation, zero volume, strict availability rejection, latched drawdown behaviour,
closure-delayed and failed exits, price-gap cap breaches, stale terminal marks,
resource/configuration rejection and isolated Decimal context. No new market
performance assessment or reserved evaluation occurs. The known A006 expected
failure remains unresolved.
