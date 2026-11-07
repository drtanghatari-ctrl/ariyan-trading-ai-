# A012 — instrument identity and contract definitions

Based on A011 checkpoint `5c90bcb`. Adds `instruments.py`, its tests and this
document. Offline metadata only. No replay, ledger, authorization, data intake,
default demo or CI implementation is changed.

## Scope and boundaries

`InstrumentIdentity(venue, venue_instrument_id)` identifies a caller-declared
listing/contract. Display symbols are labels, not unique identity. Venue and IDs
are case sensitive; aliases/renames require a future provenance mapping. IDs are
not authenticated, guaranteed unique in an actual venue, or automatically linked
to existing datasets. Identical tickers on different venues remain different.
Concrete futures maturities need distinct venue instrument IDs; the metadata
cannot independently establish that a supplied ID denotes the stated maturity.

`InstrumentSpec` is an immutable, versioned snapshot containing identity,
display symbol, asset class, product, underlying label, quote/settlement currency,
quantity and price units, contract multiplier, price/quantity step and minimum,
price domain, settlement type, calendar/timezone labels, corporate-action and
roll references, effective interval, last trade/expiry and source/observation
labels. The settlement currency denotes the monetary/PnL leg; it does not model
every delivery leg, fees in other tokens or currency conversion.

| Asset / product metadata | A012 representation |
| --- | --- |
| Crypto pairs | CRYPTO + SPOT, asset delivery, multiplier 1 |
| Traditional stocks | EQUITY + SHARE, security delivery, multiplier 1, action reference |
| Funds, including commodity exposures through funds | FUND + FUND_SHARE; separate underlying label, security delivery and action reference |
| Gold, silver and oil spot products | METAL or ENERGY + SPOT; caller must name the actual unit, listing and terms |
| Concrete futures | CRYPTO/EQUITY/METAL/ENERGY + FUTURE, positive multiplier, whole CONTRACT quantities, cash/physical settlement, last trade, expiry and explicit roll reference |

These are representable metadata combinations, not installed market adapters.
CFDs, options, perpetual swaps, fractional futures contracts, continuous futures
series and other product types are outside this schema. Do not relabel an
unsupported product as a supported one. Fund and spot/futures exposures to the
same commodity are distinct instruments, with different accounting/risk needs.

All tests use SYNTHETIC instruments. No current venue filters, contract sizes,
real listings, prices or calendars are supplied as production specifications.

## Exactness and validation

Numeric terms accept Decimal, integer or decimal string through existing bounded
validation; floats, booleans, nonfinite values and unsupported precision are
rejected. Normalized numeric terms are stored as Decimal. Steps/minimum and
multiplier must be positive; minimum quantity must be on the quantity grid.
Share products use SHARE quantity units. A future's multiplier declares the
price-denominator units per CONTRACT (for example a synthetic barrel/contract
factor when the price unit is USD_PER_BARREL); no multiplication or PnL is posted.
Non-futures require multiplier 1 and no expiry/roll terms. Futures require
effective start <= last trade <= expiry and whole-contract step/minimum.
Corporate-action references are required for equity/fund exposure and
NOT_APPLICABLE for the other A012 asset classes. A reference is a label, not proof
that a policy has been implemented or that adjustments are correct.

`validate_lattice(price, quantity)` checks only the declared price domain,
zero-origin price/quantity grids and minimum quantity. It uses exact integer
ratios, including steps such as 0.05, independently of the ambient Decimal
context. SIGNED and NONNEGATIVE domains can explicitly represent nonpositive
price observations where the caller's actual product permits them. This does
not make A007 accept nonpositive prices or implement signed-price accounting.

Passing the lattice check is never order admission. It checks no session,
effective date, expiry, inventory, margin, leverage, price bands, minimum notional,
maximum size, changing filters, liquidity, account risk or human authorization.
There is no automatic rounding, quantity sizing, PnL/notional calculation,
cash posting or conversion of units. Offset grids and tiered/dynamic tick rules
need separate schemas and adapters; this is not a universal venue validator.

`effective_at(timestamp_ms)` checks only the half-open metadata interval
`[effective_from_ms, effective_until_ms)` (open ended when None). It can remain
true after a future's last trade or expiry. It does not mean the instrument is
tradable then. Observation times may be later than effective dates for historical
records; neither timestamp proves point-in-time availability or unseen data.

Timezone labels use UTC or a region/name shape, not a fixed abbreviation. No
timezone database lookup, DST resolution, exchange calendar, holiday, early
close, suspension or halt validation is implemented. A label such as
America/New_York is not an installed calendar. A future calendar layer must
distinguish scheduled closures from genuinely missing native-time observations.

## Serialization and identity

`to_record()` emits plain JSON-compatible values, canonical decimal strings and
explicit false authenticity/executable-support flags. `spec_from_record()`
requires exact keys, version, enum strings, decimal strings and false flags;
missing/unknown keys, type confusion and upgraded claims are rejected. It
accepts a dictionary; a bounded/strict JSON-file reader is not part of A012.

Identity and specification fingerprints are domain-separated SHA-256 over sorted,
compact ASCII JSON. Numerically equivalent Decimal spellings canonicalize to
the same numeric text. Display changes leave identity unchanged but change the
specification fingerprint. Provenance/effective-time changes also change the
specification fingerprint. Hashes identify declared content; they do not establish
venue authenticity, signatures, freshness or authority. No persistent registry,
revision ordering or overlapping-effective-interval reconciliation is provided.

## Integration boundary and next work

A007's continuous epoch-aligned bars, single-symbol strategy, fixed cash/quantity
precision and spot-style PnL remain unchanged. A012 metadata is not wired into
A007, dataset provenance, order execution, authorization or portfolio risk.
Do not replay stock/futures data through the existing core and describe that as
validated multi-asset support. No live-readiness or profitability claim follows.

Next: instrument-bound dataset provenance and a validated calendar/session model;
then product-specific accounting, corporate-action/roll handling and execution
filters, realistic assessment and shared portfolio controls. Broker/exchange
connectivity and human authority remain separate requirements.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a012.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Nineteen tests cover venue identity, synthetic cross-asset metadata, concrete
futures, signed/zero prices, non-power-of-ten grids, precision/context isolation,
effective-time boundaries, canonical hashes, immutability, strict record schemas,
invalid product/type/term combinations and unchanged A007 configuration.
The known A006 expected failure remains unresolved.
