# A033 — forex and CFD instrument terms

Adds `margin_instruments.py`, its tests and this document. A012 is unchanged:
its version string, fingerprints, enums and every consumer (A013, A015, A016,
A017 and others) behave exactly as before. A012 explicitly excludes CFDs and has
no forex class, so A033 is a separate, versioned layer that reuses A012's
`InstrumentIdentity` and validation helpers. Offline metadata and exact
arithmetic only: no broker connection, no order admission, no trading authority.

## What it describes

`MarginInstrumentSpec` is an immutable, caller-declared snapshot of a margined
product:

| Field group | Meaning |
| --- | --- |
| identity, display symbol | A012 `InstrumentIdentity(venue, venue_instrument_id)`; the display symbol is a label |
| asset class | FOREX, CRYPTO, EQUITY, INDEX, METAL, ENERGY |
| product | `FX_MARGIN` (forex pairs, FOREX only) or `CFD` (every other class) |
| base label, quote currency | Forex requires distinct three-letter codes; quote currency is an uppercase label |
| contract size | Units of the base asset in one 1.00 lot |
| lot step, minimum lot, maximum lot | Lot grid; min and max must sit on the step |
| price step, pip size | Tick grid; the pip size must be a multiple of the tick |
| initial / maintenance margin rate | Fractions of notional, in (0, 1]; maintenance <= initial (1:1 is the floor, so no leverage below 1) |
| allows shorting | Strict boolean |
| financing and commission references | Required explicit labels; `NOT_APPLICABLE` is rejected because margined products carry such costs |
| calendar, timezone, effective interval | Labels only; no calendar database or DST logic |
| corporate-action reference | Required for equity CFDs, `NOT_APPLICABLE` for all other classes |

## Exact arithmetic

All helpers use integer-ratio grid checks and high-precision Decimal arithmetic
that traps any rounding, independently of the ambient Decimal context.

- `pip_value_per_lot()` = pip size x contract size.
- `notional(price, lots)` = price x lots x contract size.
- `required_initial_margin` / `required_maintenance_margin` = notional x rate.
- `profit_and_loss(side, entry, exit, lots)`: gross, long or short; short is
  refused when the instrument declares shorting unavailable.

Every figure is in the **quote currency**. Conversion to an account currency,
spread, commission, swap/financing, slippage, margin calls, stop-out, partial
fills and rounding to a broker's money precision are not modeled. The A033 numbers
are reference arithmetic, not an account ledger.

## Boundaries

- `validate_lattice` checks only grids, bounds and positive prices. It is not
  order admission and checks no session, margin availability, price band, minimum
  notional, exposure limit or human authorization.
- Prices must be positive. Products that can trade at zero or negative prices
  (some energy contracts) are not supported by this version.
- Serialization mirrors A012: exact keys, version, enum strings, decimal strings
  and explicit false `source_independently_authenticated` /
  `executable_support_established` flags. Hashes identify declared content only.
- Nothing here is wired into replay, the ledger, the Predictability Gate or any
  broker. `cash_trade_math` continues to reject non-spot products. All tests use
  SYNTHETIC instruments; no real contract sizes, margin rates or listings are
  supplied as specifications. Real broker terms must come from the broker's own
  published contract specifications and be recorded with provenance.

## Next work

1. A strategy interface and a backtester with cost, spread and drawdown metrics.
2. A margin-aware accounting layer (account currency conversion, financing,
   margin calls and stop-out) before any leveraged replay.
3. A validated session calendar for forex weeks and exchange-hours CFDs.
4. A broker-agnostic execution interface, then a demo-only MT5 adapter.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_margin_instruments_a033 -v
PYTHONPATH=app python -m unittest discover -s tests
```
