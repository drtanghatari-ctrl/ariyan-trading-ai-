# A019 — close legacy SQLite test-fixture connections

Based on A018 checkpoint `c65511b`. Changes eight existing test files and adds
one lifecycle regression guard plus this document. No production module,
ledger/transaction implementation, authorization, replay, market result, demo
or CI configuration is changed. No warning filter is installed or suppressed.

## Finding

The phone's Python 3.14 full suite completed 1,092 tests with its known expected
failure, while printing unclosed SQLite connection ResourceWarnings. The
reported `contextlib.py` frame is a collection/reporting location, not by itself
the connection's allocation site. A018's command and tests have no SQLite calls.

A temporary local diagnostic used a SQLite Connection subclass to record
allocations and actual open/closed state across the available suite. Before
the change, it tracked 537 parent-process connections: 525 explicitly closed,
12 left open. All twelve allocation paths were the following existing fixtures:

| Test file | Unclosed transaction contexts |
| --- | ---: |
| `test_durable_integrity.py` | 1 |
| `test_durable_ledger.py` | 1 |
| `test_durable_recovery.py` | 3 |
| `test_durable_schema_integrity.py` | 1 |
| `test_journal_tampering_a005.py` | 1 |
| `test_ledger_identity_a006.py` | 2 |
| `test_process_crash_recovery.py` | 2 |
| `test_schema_constraints_a005.py` | 1 |

Each used `with sqlite3.connect(...) as db:`. That transaction context commits
or rolls back when it exits, but does not itself close the connection.

## Focused fix

Each affected module imports `contextlib.closing`, and each affected context
now uses:

```
with closing(sqlite3.connect(path)) as db, db:
    ...  # Existing SQL/assertions remain unchanged.
```

The inner `db` context preserves the original commit/rollback boundary; the
outer `closing` then closes the handle even when an assertion/operation raises.
Existing explicit commits, SQL mutations, assertions and fixture semantics are
retained. Child programs deliberately killed by crash tests remain unchanged;
the fix concerns the parent test process's inspection connections.

Production DurableLedger connection handling is not modified. This change is
not a production-ledger correctness certification or a fix for the existing
A006 expected failure.

## Regression evidence

`test_sqlite_cleanup_a019.py` reruns the twelve named legacy test cases with a
tracking SQLite factory. It retains strong references, checks the real handles
reject a trivial query after the cases finish, and closes its own references in
`finally` even if the regression fails. It does not rely on warning timing or
garbage-collection heuristics. Custom factories in these target paths fail the
guard rather than silently escaping observation.

Before the fix this guard failed on exactly twelve open handles; after the fix
it passed. The temporary full-suite diagnostic then tracked 537 ordinary
connections and observed all 537 explicitly closed. The regression guard's
separate factory checked another 35 parent-process connections; those were
also closed. Deliberately terminated subprocess handles are outside that local
parent-process instrumentation.

Local lifecycle checks ran on Python 3.12; they establish the tested allocation
paths' closure independently of newer native ResourceWarning reporting. The
phone's Python 3.14 warning-enabled run remains the direct platform check.
Do not claim all possible leaks or resource warnings are eliminated solely from
the local diagnostic. A new warning should be traced rather than hidden.

The guard is one discovered unittest that exercises twelve existing cases;
its internal executions are not twelve newly independent test cases or
additional evidence of trading safety/profitability.

## Installer safeguards

The standalone installer requires the clean tracked `c65511b` checkpoint and
the expected development branch. It verifies exact hashes of all eight old
test files before writing. Its transformation is limited to adding the import
and replacing the two known transaction-context spellings; expected transformed
hashes and Python compilation are checked as well. A source mismatch rejects
without applying a generic text patch to unknown content.

Before replacement, all eight original files and an unsigned hash index are
saved in a new `work/a019-originals-*` directory. Existing user backups and
research outputs are preserved. Test replacements are staged beside their
targets, retain permission modes and use per-file replacement. New guard/docs
files are exclusively created. All ten targets are prevalidated.

Caught installation failures attempt to remove owned additions and restore
previously replaced files only when their bytes still match the installer's
expected new version. A concurrent edit is not overwritten during rollback;
an incomplete rollback is reported explicitly with the retained backup path.
This is not one crash-atomic ten-file transaction or a filesystem-lock guarantee.
If killed or interrupted outside handled cleanup, inspect git diff and the
retained originals before further work. No automatic commit/push occurs.

`--check` performs applicability checks without target or backup writes. For
normal installation, pass `--project` as with prior standalone installers.
Backups remain outside the explicitly scoped source commit.

## Checks

```
PYTHONPATH=app python -m unittest discover -s tests -p '*a019.py' -v
PYTHONWARNINGS=always::ResourceWarning PYTHONTRACEMALLOC=5 PYTHONPATH=app \
  python -m unittest discover -s tests
```

The second command enables allocation tracebacks for any remaining native
resource warnings. It does not filter warnings away, turn a warning into an
expected failure, or modify application data. All databases exercised here
are the existing tests' temporary fixtures. The known A006 expected failure
remains unresolved.
