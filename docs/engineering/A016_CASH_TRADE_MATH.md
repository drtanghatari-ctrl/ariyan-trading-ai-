# A016 — conservative cash-trade simulation arithmetic

Based on A015 checkpoint `eaddeae`. Adds `cash_trade_math.py`, twenty-one tests
and this document. No existing intake, replay, ledger, authorization, demo or CI
code is changed. No new market data, performance test or strategy promotion.

## Supported contract

`quote_cash_trade(spec, side, quantity, reference_price, *, cash_currency,
cash_step, fee_bps, slippage_bps, price_convention)` models one full cash leg.
It requires an exact A012 InstrumentSpec and explicit BUY/SELL. Only SPOT,
SHARE and FUND_SHARE with multiplier 1 are supported. Futures are rejected,
including a future with multiplier 1; multiplying spot notional is not a
substitute for derivative margin, settlement or PnL accounting.

Cash, quote and settlement currency labels must match exactly. There is no FX,
inverse-quote conversion, fee in another currency, borrowing, margin, leverage,
option, CFD or perpetual model. Metal/energy spot metadata can use the same
cash arithmetic only when the actual units and price convention meet this
contract; that is not a production commodity adapter.

`price_convention` must explicitly equal
`PRICE_CONVENTION = "QUOTE_CURRENCY_PER_ONE_QUANTITY_UNIT"`. The numeric price
must already be denominated that way. Free-text A012 price-unit labels and
this convention declaration are not independently verified. Prices quoted in
subunits, percentages, inverse units or another denomination require a verified
adapter/conversion; do not silently treat them as cash-currency unit prices.

Reference price and quantity must already fit the declared instrument lattice
and quantity minimum. Quantity is never rounded to make a trade fit. Positive
reference and modeled prices are required even if metadata declares a signed
or nonnegative price domain. All inputs use existing bounded decimal validation
(24 significant digits, 12 decimal places, supported magnitude); booleans,
binary floats and nonfinite values are rejected.

## Explicit conservative convention

Cash precision is supplied as a positive `cash_step`, not assumed to be cents.
Non-power-of-ten grids such as 0.05 use exact multiples, not merely decimal-place
quantization. Fees and slippage are explicit nonnegative values in 0..1000 bps;
neither has a default. Rebates/negative fees are unsupported.

| Component | BUY | SELL |
| --- | --- | --- |
| Adverse price before tick rounding | reference × (1 + slippage/10000) | reference × (1 − slippage/10000) |
| Modeled execution price | Round up to instrument price step | Round down to instrument price step |
| Exact modeled notional | quantity × modeled price | quantity × modeled price |
| Posted notional | Round up to cash step | Round down to cash step |
| Fee | Posted notional × fee/10000, rounded up to cash step | Same |
| Cash delta | −(posted notional + fee) | posted notional − fee |
| Units delta | +quantity | −quantity |

These are a deliberately conservative simulation convention, not an assertion
about any real exchange/broker's rounding or fee policy. All declared price
steps are zero-origin fixed grids. Dynamic/tiered ticks and offsets are not
implemented. A rounded sell price of zero, zero posted proceeds or proceeds
fully consumed by fees are rejected as dust; there is no automatic liquidation.

The result records unrounded/posted notional, their rounding adjustment and
`modeled_slippage_cost = quantity × abs(modeled price − reference)`. Tick rounding
is included in that diagnostic. Slippage is already reflected in the modeled
cash leg and must not be subtracted again; the diagnostic is not an independent
charge or guaranteed decomposition of final rounded account costs.

Rounding uses exact integer ratios. Multiplication uses an isolated 100-digit
Decimal context, sufficient for the supported bounded inputs/intermediates.
Derived price grids are checked against the supported numeric bounds again.
No ambient precision/rounding setting or binary floating-point arithmetic enters
the calculation. Equivalent decimal spellings produce the same canonical quote.

## Pure balance simulation

`simulate_cash_trade(...)` accepts the same arguments plus `opening_cash` and
`opening_units`. It computes a fresh quote and returns hypothetical closing
balances. It accepts no supplied quote to post. Opening cash must be nonnegative
and on the cash grid; holdings must be nonnegative. Cash/holdings insufficiency
is rejected rather than creating borrowing or a short position.

Existing holdings need not meet an order minimum or order lot grid. Only the
quantity traded must meet them, so residual/odd-lot holdings can remain. They
are not automatically rounded, corrected for corporate actions, sold or valued.
Closing balances must remain inside the same bounded input representation;
unsupported output magnitude/precision is rejected without silent truncation.

A quote alone does not check any account balance. Neither API admits an order.
The balance simulation checks arithmetic solvency only, not position caps,
daily loss limits, exposure, valuation, settlement timing or human authority.
There is no portfolio model, fee-currency wallet, dividend/action ledger,
session/effective-date check or session-aware replay integration.

## Example

```
from ariyan_trading.cash_trade_math import PRICE_CONVENTION, simulate_cash_trade

# spec is a separately established caller-supplied InstrumentSpec.
result = simulate_cash_trade(
    spec, "BUY", quantity="3", reference_price="10",
    opening_cash="100", opening_units="0",
    cash_currency="USD", cash_step="0.01",
    fee_bps="10", slippage_bps="10",
    price_convention=PRICE_CONVENTION,
)
```

For SYNTHETIC terms with price step 0.05 and SHARE quantity step/minimum 1,
the buy price is 10.05, posted notional 30.15, fee 0.04, cash delta −30.19.
Selling the same three units at the same reference with the same modeled costs
gives price 9.95, notional 29.85, fee 0.03, proceeds 29.82. A round trip starting
at 100 closes at 99.63: 0.30 modeled slippage plus 0.07 fees. This is a synthetic
arithmetic example, not a market backtest or current venue contract specification.

## Provenance and integration boundary

Quotes contain the full declared instrument/specification fingerprint, explicit
costs/convention, all cash-leg components and false venue-verification, actual-fill,
order-admission and authority flags. The quote SHA-256 binds all other fields
using compact sorted ASCII JSON with the `ARIYAN-A016-CASH-QUOTE-V1` domain
plus NUL. It is unsigned content identification, not an authenticated quote,
venue acknowledgement, time/freshness proof or capital authorization token.
Balance records explicitly state no ledger posting, risk approval or live authority.

The functions write no files, modify no input/ledger/account and contact no
service. Returned dictionaries are JSON-compatible reports, not trusted posting
instructions. Session schedules, source mappings, book depth, latency, actual
spread, partial fills, minimum notional, maximum orders, price bands, taxes and
venue-specific fee currencies remain outside this model.

A007's original fixed steps and half-even notional rounding remain unchanged.
A016's convention is deliberately different and is not retroactively applied
to R001–R004. No result is recomputed or compared as though the execution models
were identical. Next work can explicitly integrate these primitives into a
bounded offline session replay with data/gap and risk policies declared first.
No live-readiness or profitability claim follows.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a016.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-one tests cover hand-computed buys/sells and flat-reference round trips,
non-power-of-ten cash grids, exact rational audits, balance conservation,
solvency, residual holdings, supported products, rejected futures/FX/conventions,
input/numeric bounds, dust, context isolation, canonical records and unchanged
legacy replay steps. All terms/prices are synthetic. The known A006 expected
failure remains unresolved.
