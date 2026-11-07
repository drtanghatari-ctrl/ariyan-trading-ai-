# A026 — offline saved review catalog

Based on `aabe662`. Three additive files: `review_catalog.py`, tests and this
document. Existing inspectors, workflows, engines, ledger and authorization code
are unchanged.

## Behaviour

`build_catalog(reviews, destination)` accepts 1..8 explicit saved A024 review
directories, in caller order. Each must pass A025 inspection. The function captures
the inspected completion record and byte-matching HTML, then creates one new
portable catalog directory. No replay, original full dataset read, optimization,
market-data request, ledger posting, account connection or live action occurs.

This connects the separately bounded reviews without merging their full batch
JSON. In particular, A024's large six-job batch exceeded A021's 32 MiB report cap;
the three per-instrument reviews can now be browsed from one small index while
retaining their existing independent base/stress accounts and results.

| Output | Meaning |
| --- | --- |
| `index.html` | Summary rows in caller order and links to each detailed review. |
| `reviews/review-NN.html` | Byte-for-byte copies of inspected source HTML pages. |
| `CATALOG.json` | Source directory labels, completion/batch/page fingerprints, A025 inspection results, per-review summary rows, artifact hashes and limitations. Written last. |

The index shows each job's instrument identity, currency, return, observed close
drawdown, fees, fill count and halt state. It does not combine balances, PnL or
returns, convert currencies, rank strategies or award a passing grade. Display
rounds to six decimal places; linked pages retain exact summary values and their
existing assumptions/limitations. Count totals describe folders/jobs only, not
capital or independent validation samples.

Exact duplicate batch digests are rejected, including duplicate folder copies.
Different reports may still share data, instruments or periods; absence of an
exact duplicate does not establish independence. Source folder labels are escaped
text. Link destinations are generated local filenames, never caller-supplied URLs.
The index has no JavaScript, external fonts, images, stylesheets or remote assets.

## Usage

```sh
PYTHONPATH=app python -m ariyan_trading.review_catalog \
  --review work/btc-review work/eth-review work/sol-review \
  --destination work/market-review-index-v1
```

All source review directories must already exist. Output's parent must exist and
the output directory must be new. Symlink paths and destinations inside a source
review are rejected. Existing/racing directories are never adopted. No source
files are changed. Exit 0 means the saved catalog was built; exit 2 means rejection.
Successful completion is not strategy approval, data authentication or authority.

Open `index.html` in a local browser. Move/copy the whole catalog together with its
`reviews` folder; its links then do not require the original review directories.
The copied detail pages are portable HTML snapshots, not full A024 review folders
and cannot replace their complete scientific records. A025 inspects the original
full review folders, not this catalog format.

Actual browser/Android local-file navigation has not been visually tested in this
build environment. Some Android file viewers restrict relative local navigation;
preserve/extract the directory structure and use a browser that permits it. This
is an offline report interface, not an installed Android application or live UI.

## Bounds and snapshot limits

Up to 8 reviews, each retaining A025's own bounds, are inspected sequentially.
The catalog permits at most 32 MiB of copied HTML in total, a 2 MiB index and 1 MiB
metadata file. Review inspection performs its own bounded reads and intake
reconstruction; copied-page limits are not a bound on total verification IO or
OS memory overhead.

The completion bytes are captured before inspection and compared afterward. Each
captured page must match its recorded hash. Completion/page hashes and current
implementation file fingerprints are rechecked before directory creation and
after copying. Output bytes and directory contents are checked before metadata
is written last. Ordinary failures remove only still-owned files/directories;
replaced or unrelated concurrent files are preserved.

There is no atomic publication, power-loss durability, authentication or ongoing
monitoring guarantee. A running or interrupted output can be observed. Unsigned
metadata/digests may be consistently recreated. A source folder's inspection
status refers to that inspection, not to its continuing state: the catalog does
not continuously re-inspect original CSVs or all source artifacts after capture.
Completion/page rechecks are not an atomic snapshot and cannot exclude hostile
filesystem or change-and-restore races. Source file hashes are observations, not
loaded-code attestation. No global reservation access-control or authority gate
is added.

## Validation and retained-data check

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a026.py' -v
PYTHONPATH=app python -m unittest discover -s tests
```

Eighteen tests cover byte-matching copies/links/fingerprints, source preservation,
no replay or original input reads, order/currency separation, duplicate detection,
count/shape errors, all-review inspection, path/no-overwrite guards, label escaping
and no active/remote elements, unsupported inspection claims, capture/write/source
changes, byte caps, ordinary failure cleanup, foreign-file preservation, directory
races, Decimal isolation, portable copies, unsigned catalog hash and deterministic
CLI execution. No platform hardlink API is required.

The retained BTCUSDT/ETHUSDT/SOLUSDT A024 reviews produced one catalog with three
review links and six separate base/stress rows. Their negative returns and latched
halts were preserved exactly. No simulation or reserved performance evaluation
was rerun, and no strategy was promoted. The known A006 expected failure remains.
