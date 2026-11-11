# A034 — stateless strategy interface

Adds `strategies.py`, its tests and this document. Offline research code. It
changes no existing module and carries no trading authority.

## Contract

A `Strategy` is a deterministic, stateless rule:

- `lookback`: number of fully closed candles it needs (1..10,000).
- `target(history) -> Signal`: `history` is a tuple of `Candle`, oldest first,
  ending at the decision bar. The result is the position wanted for the NEXT bar:
  `LONG`, `SHORT` or `FLAT`.
- `describe()` returns `{name, params}` for provenance; frozen dataclass
  parameters are validated at construction.

The strategy cannot see future bars, account state, costs or a broker. The A035
backtester hands it only the last `lookback` closed candles, so look-ahead is
structurally impossible through this interface. A strategy that smuggles in
outside state or randomness is outside the contract; the backtester's
determinism test is the check for that.

## Included strategies (test fixtures, not a claimed edge)

| Strategy | Rule |
| --- | --- |
| `BuyAndHold` | Always LONG; benchmark |
| `SmaCross(short, long, allow_short)` | Fast SMA above slow -> LONG, below -> SHORT (or FLAT), equal -> FLAT. Compared by cross-multiplication, so no division or rounding |
| `Momentum(bars, allow_short)` | Close above the close `bars` ago -> LONG, below -> SHORT (or FLAT) |

No parameter selection, optimization or profitability claim exists. A new
strategy is a subclass implementing `lookback` and `target`.

## Checks

```
PYTHONPATH=app python -m unittest tests.test_strategies_a034 -v
```

Nine tests cover signals, exact comparison, window isolation, parameter and
history validation, provenance records, abstractness and immutability.
