# A041 — Forex/CFD candle CSV importer

`fx_csv.py` (`load_fx_csv`) and `fx_csv_check.py` read a candle CSV you downloaded and return a
validated `SessionCandleDataset` for the backtester and walk-forward harness. It makes no network
calls. It was tested only on synthetic files shaped like each provider's export; it has not yet
been run on a real download.

## Why it exists

The cloud workspace cannot reach data sites, and the MT5 connection was blocked by the user's
network. Historical files downloaded on the laptop are the shortest path to real backtests.

## Formats recognised (by header)

Stooq (`Date,Open,High,Low,Close[,Volume]`), Yahoo (`Date,...,Adj Close,Volume`), Dukascopy
(`Gmt time,Open,...`, `dd.mm.yyyy hh:mm:ss.fff`), MT5 export (tab-separated `<DATE> <TIME> <OPEN> ...`),
canonical A007 (`timestamp_ms`), and generic headers with date/time and open/high/low/close.
Newest-first files are sorted. Missing volume becomes 0.

## Rules (nothing is repaired)

- **Time zone is never guessed.** Naive times are read as UTC unless you pass `utc_offset_minutes`
  or `timezone_name`. MT5 server time is usually GMT+2 or GMT+3 and changes with daylight saving;
  a fixed offset is wrong for part of the year. Prefer UTC exports (Dukascopy GMT, Yahoo/Stooq daily).
- **Bad rows** (`null`, high below low, zero price) raise with the line number, or with
  `--skip-bad-rows` are skipped and listed.
- **Outside-session bars** (for example Saturday) are dropped and counted.
- **Gaps inside a session** are never filled. The longest gap-free run is kept and every run is
  reported, so you can see how much data was lost.
- **Last bar dropped** by default (it may be unfinished).
- **Default sessions** are a declaration, not truth: intraday = Sunday 17:00 to Friday 17:00 New York
  (DST aware); daily = Monday to Friday UTC. Providers cut FX days at different times, so daily bars
  are approximate. Holidays are unknown; a provider that omits Christmas will show up as a gap.
- Up to 100,000 bars (about 16 years of H1, one year of M5). Older bars are cut and reported.

## Check a file on Windows

```
set PYTHONPATH=app
python -m ariyan_trading.fx_csv_check C:\Users\you\Downloads\EURUSD.csv --symbol EURUSD
```

Add `--utc-offset-minutes 120` for MT5 exports at GMT+2. Send the printed summary back; it contains
no personal data.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_fx_csv_a041 -v
```
