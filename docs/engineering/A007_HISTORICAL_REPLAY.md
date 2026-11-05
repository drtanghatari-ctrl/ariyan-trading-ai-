# A007 — offline historical-market replay

Built on source checkpoint `37afa41123916ce80be2aafa2c8c17211c4d2c02`.

This is an evaluation feature, not a live trader or a completed V1. It adds
market-data intake and a reproducible single-symbol replay without editing the
protected ledger, authorization modules, legacy engine or default A006 demo.
The existing standard-library test workflow discovers the new tests.

## Run the real-data smoke example

From the repository root, after installing the A007 package:

```bash
mkdir -p work
PYTHONPATH=app python -m ariyan_trading.replay \
  --csv examples/a007/BTCUSDT-1h-2024-01-01.csv \
  --format binance-spot --timestamp-unit ms \
  --symbol BTCUSDT --interval-ms 3600000 \
  --source 'Binance public spot klines, BTCUSDT, 2024-01-01, 1h' \
  --as-of-ms 1704153600000 \
  --output work/a007-btc-20240101.json
```

Output creation is exclusive. Choose a new output filename if it already exists.
The example contains 24 actual hourly candles, suitable for an integration smoke
check only. It is not evidence of out-of-sample performance or profitability.
Source URLs, original ZIP and CSV hashes, and the published ZIP checksum are
recorded in `examples/a007/SOURCE.json`. A matching checksum from the same
provider confirms transfer consistency, not independent market-data authenticity.

## Intake contract

Canonical CSV has exactly this header and no extra columns:

```text
timestamp_ms,open,high,low,close,volume
```

Times identify bar opens in UTC epoch milliseconds. The caller supplies a
fixed duration with `--interval-ms`. Bars must be aligned to epoch multiples of
that duration, contiguous, unique, strictly increasing, and fully closed by
`--as-of-ms`. Without that flag, the current system time is captured in the
report. Use an explicit cutoff to reproduce identical report bytes.

Only fixed-duration, epoch-aligned intervals are supported. Weekly/calendar
bars with other alignment and calendar months require an explicit future
adapter. No sorting, interpolation, timestamp-unit guessing or gap filling occurs.

The `binance-spot` adapter accepts headerless twelve-column public klines. It
uses open/OHLCV and checks close time against the interval and explicit `ms`
or `us` timestamp unit; the other five fields are not used in replay. Binance
documents microsecond spot timestamps from January 2025 onward:
https://github.com/binance/binance-public-data

The loader hashes the exact input bytes. Symbol and source labels are caller
assertions, not inferred from a filename or verified against a live exchange.
Limits: 32 MiB per CSV, 100,000 candles, finite bounded Decimal fields, positive
OHLC prices, nonnegative volume, and consistent OHLC ranges. Raw numeric fields
use at most 24 significant digits and 12 fractional places and are <= 10^15.

## Strategy and execution

- The strategy compares the short and long moving-average *levels* (defaults
  3 and 5 closes). It repeats BUY while the short mean is higher; it is not a
  crossover-only system and does not claim an investment edge.
- A decision is computed after each completed candle. Its earliest modeled
  fill is the following candle's open with fixed adverse slippage.
- Fill sizing uses only that open, prior portfolio state, configuration and
  the prior completed candle's volume. Current-bar high, low, close and final
  volume are unavailable at the open and never control that fill.
- A prior zero-volume bar skips the next fill. Positive prior volume is not
  proof of current liquidity; the model can still assume an unfillable trade.
- BUY cash outlay (notional plus fee) is capped at the configured fraction of
  pretrade marked equity and available cash. Position exposure is capped as a
  fraction of equity *after* costs, marked at the reference open. Both caps
  must hold. Later price gaps may exceed the cap. SELL exits the whole position
  and is not restricted by the BUY allocation cap.
- Quantities round down to eight places; notional rounds half-even to cents;
  positive fees round up to cents. Binary search chooses a quantity satisfying
  both caps under these posting rules. Dust trades with zero notional are skipped.
- No shorting, leverage, intrabar stops, partial fills, market impact, venue
  filters, tick-size handling or live order submission is implemented.

The report contains data provenance labels/hash, parameters, every filled order,
per-bar decisions and equity, fees, a slippage diagnostic, marked P/L, return
and maximum close-to-close drawdown relative to running peak including initial
capital. Slippage is already reflected in fill prices; do not subtract the
diagnostic again. Final holdings are marked at the last close without assumed
liquidation or final exit costs.

The baseline makes one full-allocation BUY attempt at the same first eligible
open, using the same costs and liquidity rule, and then holds. It does not
search ahead after an unavailable first fill. Its greater exposure is disclosed;
the comparison is not risk matched or proof of alpha.

## Verification and boundaries

```bash
PYTHONPATH=app python -m unittest discover -s tests -p '*a007.py' -v
PYTHONPATH=app python -m unittest discover -s tests
PYTHONPATH=app python -m ariyan_trading
```

Tests cover a hand-calculated round trip; cost and balance identities; post-cost
risk caps; caller Decimal-context isolation; prefix invariance when future data
changes; exclusion of current-bar final data from fills; malformed/duplicate/
gapped/incomplete bars; ms/us timestamp handling; and fresh-process CLI failures,
deterministic reports and no-overwrite behavior.

This milestone does not close A006 authorization/trust work. Live integration
still requires its unresolved boundaries, operational STOP/FREEZE and risk
governors, independent reconciliation, appropriate market-data checks, strategy
and predictability validation, and explicit human authority. The archival master
ZIP remains a reference archive, not integrated runtime code.
