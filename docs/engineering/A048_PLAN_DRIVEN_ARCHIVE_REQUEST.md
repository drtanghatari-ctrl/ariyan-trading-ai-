# A048 derive the archive request from a frozen plan

Inspect the exact A010 request without accessing the network:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_archive_request \
  --plan work/p001/plan.json
```

The command verifies the A036 fingerprint and derives the symbol, fixed
candle interval, inclusive start and end months, and explicit cutoff from
the plan. The frozen window must align to complete UTC months and require
canonical millisecond candles. A010 validates the supported interval,
market symbol, request duration and candle count.

After the window closes and all archives are available, use a new
snapshot directory under an existing parent:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_archive_request \
  --plan work/p001/plan.json --fetch-output work/p001/binance-snapshot
```

Only `--fetch-output` requests network access. The command rejects this
option before the local clock reaches the frozen end. Reaching the end
does not establish archive availability. Fetching delegates checksums,
canonicalization, and snapshot publication to A010. A047 can consume the
result later with `--binance-snapshot`. A048 does not run replay or change
trade admission.
