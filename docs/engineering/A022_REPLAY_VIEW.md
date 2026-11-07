# A022 — offline saved replay report viewer

Based on `7190166`. Three additive files: `replay_view.py`, tests and this document.
No existing application, ledger, authorization, engine or batch code is changed.

## Function

Read one saved A021 batch and create a standalone HTML review. This does not run
a new replay, fit a model, access original CSV/metadata inputs, read keys, post a
ledger entry, connect an account or request network data. It does not evaluate
original reserved performance or promote any research strategy.

The page provides a separate result row and card for every job, preserving manifest
order and currency. It shows venue-qualified identity, caller display symbol,
asset/product, source label, return, observed close drawdown, fees, simulated fill
count, opening cash, final marked equity, terminal units and last mark time.
Halt and stale-mark badges remain visible when applicable. There is no combined
balance, portfolio return, ranking, passing grade or profitable-strategy badge.

Expandable sections retain exact summary/configuration values, input fingerprints,
source label and batch/replay/intake limitations. Quick display rounds to six
decimal places; exact JSON values remain in the summary section. Fees and modeled
slippage are already reflected in fills and are not deducted again by the viewer.

Charts use inline SVG with opening cash and **every saved observed close**, at
native elapsed-time coordinates. No resampling occurs. The dashed line represents
opening cash. The vertical range follows each job's own observed values with
padding, so chart slopes/heights are not cross-job risk comparisons. Joins between
observations do not establish intrabar values, returns during closures or fills.
The requested time range remains on the horizontal axis, including a blank tail
when the last observed mark precedes the requested end.

## Usage

After explicitly producing an A021 batch from permitted inputs:

```sh
PYTHONPATH=app python -m ariyan_trading.replay_view \
  --report work/batch-results.json --output work/batch-review.html
```

Open the resulting HTML with a local browser. It has no JavaScript, external fonts,
images, stylesheets or network resources, and requires no server. Native HTML
details controls expose additional information. Responsive CSS rearranges the
cards for narrow screens; the summary table scrolls horizontally within its box.
No file access, uploads, logins, account buttons or order controls exist in the page.
It is a saved-report viewer, not an installed Android application or live dashboard.

Existing output files are never overwritten. Output's parent must already exist.
Input/output symlinks and symlink path components are rejected. Input JSON is
bounded to 32 MiB, HTML to 16 MiB, jobs to 8, saved curve points to 10,000 per job
and 40,000 overall, and saved fills to 1,000 per job. Text, numeric and list fields
have explicit bounds. API `render_report(report)` returns UTF-8 HTML bytes;
`write_view(report_path, output)` writes exclusively and returns job count.

Exit 0 means a supported saved report was rendered. It does not certify a market,
strategy, execution model or live readiness. Exit 2 means rejection without a
successful HTML output. Input bytes are rechecked before exclusive output creation.
Ordinary write failures remove the file owned by that write; an existing or racing
file at creation is preserved. Atomic snapshots, power-loss durability and hostile
filesystem publication protection are not established, as in A018/A021.

## Consistency checks and limits

The viewer checks the exact supported A021 top-level contract, unsigned batch
digest, job IDs/counts, declared identity fingerprints, supported cash configuration,
required authority flags, bounds and fields used for display. It compares repeated
summary rows against their job summaries, terminal balances against the final
curve point, net PnL/return against opening/final equity, drawdown against saved
observed equity/peak, recorded fee/slippage sums against saved quote fields, and
mark/halt/count consistency. Plot arithmetic uses a fresh Decimal context.

This is deliberately a **displayed-field consistency check**, not full report
authentication or independent replay validation. The original OHLCV inputs,
signals, decisions, fills, price/quantity grids, underlying quote computations,
nested hashes and all possible nested metadata relationships are not reverified.
The viewer does not establish exchange calendars, corporate actions, source truth,
key authority, independent rollback resistance, out-of-sample status or statistical
adequacy. A caller can edit a consistent report and recompute its unsigned digest.
The visible footer explicitly states these limits. A matching digest is not a
signature or authorization object.

All rendered caller text is HTML-escaped, including source labels, instrument
display symbols, limitations and JSON details. SVG coordinates derive solely
from bounded numeric/time fields. A restrictive content security policy disables
scripts, remote resources, forms and base URLs; it is defense in depth, not a
substitute for escaping. No key or credential fields are read or requested.

## Checks

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a022.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Twenty-three tests cover replay-free operation with original inputs absent,
unsigned hashes, summary/curve/cost consistency, identity/schema/type/count and
authority rejection, HTML injection, no active/remote elements, full/time-spaced
curve points, tiny/flat numeric ranges, halt/stale-mark notices, exact details,
deterministic processes, Decimal isolation, byte limits, symlinks/no-overwrite,
input-change detection, creation races, partial write cleanup and CLI failures.
The retained real BTC 24-candle fixture is integration smoke only, using unverified
terms/calendar; synthetic fixtures are not trading evidence. No `os.link` fixture
is needed. A006's known expected failure remains unresolved.

HTML structure and responsive CSS are tested. A browser visual check could not
be completed in the build environment because a Chromium executable was unavailable
and its download failed; actual Android/browser layout remains to be checked.
