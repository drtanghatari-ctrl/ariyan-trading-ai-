# A010 — public archive intake and retained provenance

Installation base: 151a972 (A009, CI green). Adds binance_archive.py, offline tests,
this document and MULTI_ASSET_SCOPE.md. A007/A008/A009, ledger, authorization,
default demo and CI are unchanged. Only an explicit fetch command uses the
network; it reads public data without API keys, account access or order endpoints.

## Adapter contract

BinanceSpotRequest(symbol, interval, start_month, end_month, as_of_ms) accepts
1..24 complete UTC calendar months with an explicit cutoff at or after the last
month's close. Symbols are configurable uppercase alphanumerics, not a fixed BTC
list. Supported epoch-aligned durations run from 1m through 1d (see CLI choices).
Weekly/calendar bars, 3d, futures, other exchanges and equity sessions are excluded.
The preflight rejects requests exceeding A007's 100,000 rows before downloading.

acquire_snapshot(request, output) requires a new directory under an existing
parent. For each requested month it obtains the provider .CHECKSUM and ZIP over
HTTPS with standard TLS verification, a 30-second socket idle timeout, bounded
responses and no redirects. There is no retry or access-restriction workaround.
The adapter verifies the ZIP's SHA-256 and exact checksum filename, permits only
one correctly named CSV ZIP member, reads without path extraction, and rejects
encrypted/unsupported members. Size limits: 512-byte checksum, 8 MiB ZIP, 32 MiB
uncompressed CSV, 64 MiB combined retained source bytes, 32 MiB combined canonical
CSV. Network idle timeout is not a whole-request wall-clock deadline.

A007 validates every monthly source CSV. In addition to gaps/duplicates/OHLC/unit
checks, A010 requires exact first/last timestamps and row count for the requested
complete month. A partially listed market month is rejected rather than padded.
Source timestamps are explicitly ms before 2025-01 and us from 2025-01 according
to the provider documentation. The adapter normalizes to canonical milliseconds
and joins only complete contiguous months; it never interpolates missing bars.

The new snapshot contains candles.csv, SOURCE.json, and each original ZIP,
.CHECKSUM and decompressed source CSV. The manifest retains request, instrument
labels, exact archive/checksum/source/canonical byte hashes, URLs, units, bounds,
row counts and local UTC acquisition time. The whole canonical file hash can be
bound into an A009 plan. Archive checksums supplied by the same provider establish
transfer consistency, not independent data truth or authenticated instrument
identity. Source labels and acquisition time remain unsigned assertions.

verify_snapshot(folder) is fully offline. It rechecks retained checksums/ZIPs,
compares retained source CSVs, rebuilds canonical data, and compares the whole
manifest including types. Missing/extra files, symlink files, changed bytes,
duplicate manifest JSON keys and oversized manifests are rejected. A coherently
recreated unsigned bundle can still verify; this is not an external trust anchor.

## Fetch and verify a larger real snapshot

From the project root, choose a new output directory if this one exists:

```bash
mkdir -p work
PYTHONPATH=app python -m ariyan_trading.binance_archive fetch \
  --symbol BTCUSDT --interval 1h \
  --start-month 2024-01 --end-month 2024-12 \
  --as-of-ms 1735689600000 \
  --output-dir work/a010-btcusdt-1h-2024

PYTHONPATH=app python -m ariyan_trading.binance_archive verify \
  --snapshot work/a010-btcusdt-1h-2024
```

The expected complete calendar coverage is 8,784 hourly candles for leap year
2024; that is not a statistical adequacy threshold. ETHUSDT and SOLUSDT use the
same command with their own symbol and new destination. Each snapshot remains
single-symbol; no cross-symbol profit, portfolio or correlation result is implied.
Historical data access is unknown. This command does not create an A009 plan,
run replay, reveal reserved performance, optimize parameters or approve trading.

## Failure/publication behavior

All download/validation work occurs in an owned temporary directory. Invalid or
incomplete downloads do not create the final directory. Publication claims the
new destination exclusively and writes SOURCE.json last. Ordinary exceptions
remove files created by that publication; an existing destination is preserved.
A process kill or power failure can leave a partial bundle. Presence alone is
not validity: offline verification must pass before use. No authenticated,
crash-safe publication or fsync guarantee is asserted. Failed fetches do not
resume; choose a fresh destination after reviewing any partial output.

## Verification

```bash
PYTHONPATH=app python -m unittest discover -s tests -p '*a010.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Sixteen offline tests cover multi-month/unit transition, multiple symbol labels,
A009 integration, request bounds, checksum/member/CSV failures, network/disk
failures and cleanup, destination races/no overwrite, changed files/strict
manifest types, symlinks, CLI behavior, and bounded HTTPS/no redirects. Synthetic
archive fixtures are tests only, never supplied as historical market evidence.

Local regression uses saved 4605f51 plus A009 and A010 additions, with A008 absent
from that archive: 918 tests, OK with one known A006 expected failure. Verify the
full target 151a972 checkout on-device before committing (expected 929 tests if
no other tests changed). Real-provider integration results and hashes are retained
separately with downloaded snapshots; they are intake evidence, not profitability.

Real-provider integration completed on 2026-11-07: BTCUSDT, ETHUSDT and SOLUSDT
each yielded 8,784 hourly candles for 2024. All 12 monthly checksums per symbol
matched, and each retained bundle passed offline re-verification. A separate
BTCUSDT December 2024/January 2025 bundle passed with 1,488 candles and source
units ms/us; its December overlaps the full-year BTC data. These are not
independent performance results. Exact hashes and source files are retained in
ATAI_A010_REAL_DATA_AND_PLANS.zip with VALIDATION.json.

The data archive also contains A009 plans fixed before this session calculated
any performance: January-September development (6,576 candles) and
October-December reserved (2,208). They record existing SMA/cost/risk defaults,
unknown prior access and NOT_ESTABLISHED out-of-sample status. No performance
evaluation has been run. Plans are beside snapshot directories so strict bundle
verification still rejects extra files within each snapshot.

## Next work

Choose and record evaluation settings/ranges before inspecting performance.
Connect the development range to A008 with its own cold start, record the exact
consumed data, and keep the reserved range out of performance evaluation until
its declared use. A009 remains a record, not a runtime access-control gate.
No adequate sample size, profitable strategy or operational V1 has been established.

Provider specification checked on 2026-11-07:
https://github.com/binance/binance-public-data/blob/master/README.md
The provider documents monthly paths, .CHECKSUM files, 2025 spot timestamp units
and possible later archive updates. See MULTI_ASSET_SCOPE.md for planned market
coverage and the boundaries of the currently implemented spot adapter.
