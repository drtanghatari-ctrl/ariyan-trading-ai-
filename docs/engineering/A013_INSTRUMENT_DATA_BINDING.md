# A013 — explicit instrument-to-dataset binding

Based on A012 checkpoint `e8268ed`. Adds `instrument_data.py`, twenty tests and
this document. Existing data loaders, instrument definitions, dataset plans,
replay, accounting, authorization, demo and CI implementations are unchanged.
No market performance is measured and no trading authority is created.

## Contract

`build_instrument_binding(dataset, spec, *, expected_symbol, price_basis,
volume_unit, binding_source)` accepts exact A007 `CandleDataset` and A012
`InstrumentSpec` types and rechecks their invariants. It records the full
specification and its identity/specification fingerprints, source metadata,
current candle boundaries/count and two separate provenance hashes.

The caller must explicitly supply the dataset symbol being mapped. It must
equal `dataset.symbol`; it need not equal the instrument's display symbol.
No venue or contract identity is inferred from a ticker. The mapping remains
`CALLER_DECLARED_NOT_INDEPENDENTLY_VERIFIED`. Matching a label does not establish
that the source actually describes that instrument, venue or contract maturity.

The only supported price-basis declaration is
`RAW_UNADJUSTED_SINGLE_INSTRUMENT`. Adjusted stock series, continuous/rolled
futures, synthetic composites and unsupported product forms need their own
provenance/normalization contracts. A013 cannot inspect prices and independently
prove that they were unadjusted; this remains an explicit caller assertion.

Volume must be declared in the instrument's `quantity_unit`. A different source
volume convention requires a separately verified adapter/conversion. Aggregate
candle volume is not an order quantity, so the order minimum and quantity grid
are NOT applied to volume. Zero volume is retained. Volume units, venue and
underlying are recorded, not independently authenticated.

## Domain and temporal checks

All supplied OHLC prices must fit the declared price domain and zero-origin
price step, using exact integer ratios without ambient Decimal rounding.
Prices are not rounded, snapped or repaired. The existing A007 OHLC validation,
positive-price restriction, chronological continuity and closed-bar rules remain
in force. Declaring SIGNED prices in A012 does not make A007 accept negative
candles or implement derivative accounting.

One specification must cover every complete candle interval: first open must
not precede `effective_from_ms`, and last close may equal but not exceed the
exclusive `effective_until_ms` when present. Futures observations must also
end no later than the declared `last_trade_ms`. A bar straddling a specification
change or last-trade boundary is rejected. No automatic multi-revision stitching,
resampling, rollover, corporate-action adjustment or calendar repair occurs.
Dataset timestamps/as-of must remain within A012's millisecond date bound.

An as-of time may be later than the effective interval for historical data.
Recorded source observation times and effective dates do not prove information
was available at a past forecasting decision. Calendar/timezone/action/roll
references are labels; their correctness and implementation are not verified.

## Hashes and verification

`recorded_raw_sha256` preserves `dataset.raw_sha256` exactly. A013 does not open
or rehash the original source file. In A007/A008-style subsets that field can
still identify the full parent input bytes. A013 never relabels it as a hash of
the current subset or as independently checked original bytes.

`candle_content_sha256` is a separate SHA-256, domain separated with
`ARIYAN-A013-CANDLE-CONTENT-V1` plus NUL. It hashes compact sorted ASCII JSON of
the interval/count followed by newline-delimited arrays of timestamp and
canonical decimal OHLCV values. Equivalent decimal spellings and signed zero
volume canonicalize identically. Candle selection or value changes alter the
content hash even if the inherited raw hash is unchanged. This is a canonical
value hash, not a source-byte hash. Dataset/source labels are bound in the full
binding rather than in this value hash.

`binding_sha256` covers every other binding field, domain separated with
`ARIYAN-A013-BINDING-V1` plus NUL. Fingerprints are unsigned content identifiers,
not signatures, trusted capture-time evidence, provenance authenticity or
freshness proof. A caller able to replace data, terms and the binding can build
another self-consistent record. No persistent registry or authenticated
publication anchor is supplied.

`verify_instrument_binding(dataset, spec, binding)` rebuilds the record and
compares every field using JSON type-sensitive encoding. Unknown/missing keys,
modified rows/metadata, venue/terms changes, upgraded flags, stale hashes and
type confusion fail. This confirms consistency with the supplied objects and
declarations, not independent venue truth or authority.

`read_instrument_binding(path)` is only a bounded (64 KiB), strict JSON parser:
it rejects duplicate keys, nonfinite constants and non-object roots. It does
not verify a binding; call the verifier with the actual dataset/spec separately.
`write_instrument_binding(path, dataset, spec, binding)` verifies first, then
creates output exclusively and never overwrites an input or earlier record.
Symlink file/parent paths are rejected. A caught write failure removes its own
partial file; no fsync, crash-safe publication or concurrent-adversary guarantee
is claimed. It does not create parent directories.

## API workflow

```
from ariyan_trading.instrument_data import (
    PRICE_BASIS, build_instrument_binding, verify_instrument_binding,
    write_instrument_binding, read_instrument_binding,
)

# dataset is independently loaded/validated; spec is a separately established
# caller-supplied InstrumentSpec. Neither is inferred from a display ticker.
binding = build_instrument_binding(
    dataset, spec, expected_symbol=dataset.symbol,
    price_basis=PRICE_BASIS, volume_unit=spec.quantity_unit,
    binding_source="Caller mapping record; independent verification pending",
)
write_instrument_binding("work/instrument-binding.json", dataset, spec, binding)
verify_instrument_binding(dataset, spec, read_instrument_binding("work/instrument-binding.json"))
```

No default instrument or production venue contract terms are installed. Tests
use synthetic terms/mappings. The existing 24-bar real BTC fixture supplies an
integration smoke only, with explicitly synthetic metadata; it authenticates
no venue specification or mapping and measures no performance.

## Integration boundary and checks

Bindings are optional and not consumed/enforced by A007, A009, replay, orders,
authorization or ledger interfaces. Those APIs remain directly callable.
Explicit false flags retain this distinction. A013 supplies no trading calendar,
stock/commodity adapter, corporate-action/roll engine, accounting, portfolio
risk or profitability/predictability decision. Reserved performance remains
unevaluated. Next work is a validated calendar/session contract and
instrument-aware intake, followed by product-specific accounting/execution.

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a013.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty tests cover explicit identity mapping, exact term/value/metadata binding,
parent/subset hash distinctions, canonical values, effective and last-trade
boundaries, every OHLC grid, aggregate-volume semantics, strict schema/JSON,
false claims, no overwrite, failed-write cleanup, symlink rejection, hostile
Decimal contexts and real-fixture integration. The known A006 expected failure
remains unresolved.
