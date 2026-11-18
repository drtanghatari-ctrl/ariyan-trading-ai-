# Carry idea: stopped at the idea gate (no backtest run)

2026-11-18. The user supplied eight policy/call-money rate series (FRED, `research/rates/`). Before writing any protocol I applied gate step 2 (cost arithmetic, `IDEA_GATE.md`) by comparing the interest-rate gap that carry would earn with what this broker actually credits, using the swap table measured on 2026-11-17 (`research/costs/litefinance_demo_2026-11-17.json`).

Latest rates used (percent a year): USD 3.88 (2026-11-16), GBP 3.73, JPY 1.23, AUD 4.60, CAD 2.27, CHF -0.33 (all Oct 2026), EUR 1.93 (series ends Jan 2026), NZD 4.33 (series ends Dec 2024, stale, treat NZD as unreliable).

Favourable side of each pair (long the higher-yielding currency), per year on notional:

| Pair | Theoretical carry | Broker credits | Broker keeps |
|---|---|---|---|
| USDCHF long | +4.21% | +0.98% | ~77% |
| USDJPY long | +2.65% | +0.78% | ~71% |
| USDCAD long | +1.61% | +0.95% | ~41% |
| EURUSD short | +1.95% | +0.08% | ~96% |
| AUDUSD long | +0.72% | +0.07% | ~90% |
| GBPUSD (either side) | +0.15% | -0.79% | the broker charges both sides |

Result: after the broker's markup, the best carry position earns about 1% a year on notional. A volatility-matched USDCHF position has about 8.7% annual volatility, so the carry alone is worth a Sharpe ratio of roughly 0.1, which no test on 10 to 12 years of data could separate from zero (see the sample-size check in IDEA_GATE.md: a Sharpe of 0.5 already needs ~25 years). Carry also has crash risk, and the broker's swap is today's snapshot.

Decision: gate step 2 fails. No protocol, no backtest, no trial counted. Reconstructing historical swaps from these rates is not needed and would add a guessed markup. The rate files stay in the repo only for reference. A different broker or account type with swap close to the interbank rate would change this; it would need its own measured swap table.
