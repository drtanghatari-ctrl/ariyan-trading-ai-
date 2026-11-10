# A039 check the declared replay source revision

Run from an ATAI Git checkout with the frozen A036 plan:

```sh
PYTHONPATH=app python -m ariyan_trading.validation_engine --plan plan.json
```

The command verifies the plan fingerprint and looks up its declared full
commit ID in the local Git object store. It compares the checkout bytes of
A007 replay, A008 evaluation, their repository-local dependencies, and the
package initializer against the regular source blobs in that commit. Success
prints `ENGINE_SOURCES_MATCH`, the commit ID and the covered paths. Errors
exit with status 2.

An older commit can match while unrelated files and HEAD have changed. Missing
Git objects or sources, local edits to covered files, and line-ending conversions
cause the check to fail. The command requires a local copy of the declared
commit and its source blobs. Git replacement objects and network fetches are
disabled for this check.

This compares source files at the time of inspection. It does not attest
which code produced a saved report, the interpreter or its bytecode cache,
or whether the commit is independently trusted. The A037 report format,
A038 report reproduction and A027 trade decision keep their existing contracts.

```sh
PYTHONPATH=app python -m unittest discover -s tests -p '*a039.py' -v
```
