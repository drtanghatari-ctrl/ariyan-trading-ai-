# A036 / A037 — account-currency conversion and session-aware data

Adds `fx_conversion.py`, `session_candles.py`, backtest integration and tests.
Offline research only. These remove two limits recorded in A035: money was
assumed to be in one currency, and every gap in the data was rejected.

## A036 — account-currency conversion

The account currency (`BacktestConfig.account_currency`, default: the
instrument's quote currency) holds balance, margin, commission and financing.
Prices and P&L arise in the quote currency and are converted per bar.

A path is a tuple of `ConversionLeg(dataset, from_currency, to_currency, inverted)`:

- `inverted=False`: the series price is `to` per 1 `from` (GBPUSD for GBP -> USD).
- `inverted=True`: the series price is `from` per 1 `to` (USDJPY for JPY -> USD).
- Legs chain, so JPY -> USD -> EUR uses USDJPY then EURUSD. Legs must start at the
  quote currency, end at the account currency and chain without gaps; legs are
  rejected when the currencies already match.

Rate use per bar: entries and exits at signal use the leg's open; marks use the
close; stop-out tests are pessimistic: losses convert at the bar's highest
account-per-quote rate, gains at its lowest. Every main timestamp must exist in
every leg or the run is refused. Each trade records `fx_open` and `fx_close`;
provenance lists every leg's symbol, source and hash.

Arithmetic uses 50 significant digits; inverting a price (1/price) is the only
inexact step. Commission and financing inputs are account-currency amounts per
lot; `spread` stays in price units.

## A037 — sessions and gaps

`SessionCandleDataset` accepts a gap between candles only when every absent grid
slot is **positively declared closed** by an exhaustive `SessionSchedule`. A
missing slot that is inside a session, crosses a session boundary, is merely
unlisted (partial coverage) or lies outside coverage is rejected, never repaired.
Observed candles must fall in a session. `slice_dataset` cuts a dataset for
train/test windows while keeping the parent hash.

Schedule builders use the IANA time-zone database, so daylight-saving changes are
computed, not assumed:

- `daily_session_schedule(...)`: exchange-style local open/close on chosen
  weekdays, with caller-supplied holidays and early closes (stocks, indices).
- `weekly_session_schedule(...)`: a continuous weekly session such as forex,
  Sunday 17:00 to Friday 17:00 New York.

Holidays, early closes and halts are **caller declarations**; no calendar data is
bundled and none is verified. A wrong schedule gives wrong data validation.

In the backtester, orders decided before a closure fill at the first open after
it, and a gap through a stop-out level liquidates at the bar's adverse extreme
(not smoothed). `financing_basis='BARS'` charges per bar held; `'ELAPSED'`
charges every grid slot including closed ones, which approximates overnight and
weekend swap. Broker-specific multipliers (for example triple Wednesday swap)
are not modeled.

## Remaining limits

- Conversion rates come from the supplied candles, not from the broker's own
  conversion; spreads on the conversion leg are not charged.
- Sharpe is computed per bar and ignores that gaps change bar spacing.
- One instrument per run; portfolio risk across instruments is not implemented.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_fx_conversion_a036 tests.test_session_backtest_a037 -v
```
