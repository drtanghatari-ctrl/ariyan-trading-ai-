# ATAI — multi-market scope (user direction, 2026-11-07)

The intended system covers multiple crypto pairs and venues, traditional stocks,
gold, silver and oil. Crypto remains the first validated implementation. Add the
other adapters when the relevant foundation is ready; their absence must not be
presented as support or allowed to obscure V1 progress. Profitability validation,
capital survival and explicit human authority remain priorities for every market.

## Current implementation and extension boundary

A007 provides a shared OHLCV representation and spot-style, single-symbol,
long-only offline test replay. A009 records dataset hashes and experiment ranges.
A010 isolates Binance public spot archive intake from those modules and writes
canonical OHLCV. Its symbol is configurable; it does not hardcode BTC. It does
not add another exchange, concurrent multi-instrument trading, shared portfolio
risk, account connectivity or live trading.

A007 currently requires continuous epoch-aligned bars. Exchange closures cannot
be silently filled or treated as corrupt equity data. Before stocks or other
session-based instruments use this core, add a validated calendar/session model.
The current fixed cash/quantity steps and spot P/L assumptions are also not a
universal execution/accounting model.

| Market | Required adapter-specific work before claiming support |
| --- | --- |
| Crypto pairs and venues | Venue-qualified instrument identity, quote/settlement currency, venue filters, fees, liquidity, market-data quality and reconciliation. |
| Stocks | Exchange calendars, timezone/DST, instrument identifiers, corporate actions/adjustments, delistings and survivorship, currency and execution rules. |
| Gold and silver | Choose the actual product (spot, fund, CFD or futures), venue, unit, currency, sessions, costs and contract rules. A generic metal price is not a tradable instrument. |
| Oil | Choose product/contract and venue; handle contract size, expiry/roll, sessions, settlement and valid price domain. Continuous price series need an explicit roll/adjustment policy. |

Futures, CFDs, ETFs and spot instruments with similar names are distinct products.
Contract multipliers, margin/leverage, shorting and settlement require their own
validated accounting and risk controls. No stock calendar, derivatives, broker
or cross-asset portfolio feature is included in A010.

Preserve the sequence: validate data and instrument semantics, realistic costs,
predictability/no-trade behavior and survival controls, then obtain the required
human authorization before any live integration. A passing unit suite or public
archive checksum is not market validation or authority to trade.
