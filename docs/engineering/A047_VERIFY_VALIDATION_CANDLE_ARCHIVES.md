# A047 replay a verified A010 archive snapshot

Use `--binance-snapshot` in place of `--csv` for report creation or
reproduction:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_evaluation \
  --plan plan.json --binance-snapshot snapshot/ --output evaluation-report.json
```

A047 reruns A010's offline verification, including rebuilding the canonical
CSV from the retained ZIPs and checksums. The snapshot must match the frozen
symbol, candle interval, format, timestamp unit, and exact window. This
accepts complete UTC months as supported by A010. The report records both
the plan's source label and the archive's source label.

A047 checks the hash of the actual candle bytes loaded for replay against
the verified snapshot. The report includes an `archive_snapshot_check`
with that hash, the archive instrument, and the manifest fingerprint.
The latter is SHA-256 over the verified manifest object encoded as
compact ASCII JSON with sorted keys and no trailing newline. Keep the
complete snapshot to reproduce the report.

For P001, the A010 request covers December 2026 through February 2027 at
one-hour resolution. Once the complete archives are available, retain
the snapshot separately from the plan and timestamp receipt. Use the
A046 timestamp options together with `--binance-snapshot` to record
both checks in the same A047 report.

An A010 snapshot has unsigned source metadata and provider checksums.
A047 establishes consistency with retained archives. Independent market
data authentication, prospective results, and trade admission remain
separate. The Predictability Gate continues to return `NO_TRADE`.
