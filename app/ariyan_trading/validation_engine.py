"""Compare local A007/A008 source files with a frozen plan's Git revision."""

import argparse
import os
import re
import subprocess
from pathlib import Path

from .validation_plan import load_plan

# Keep this list aligned with the repository-local imports of A007 and A008.
ENGINE_PATHS = tuple(
    f"app/ariyan_trading/{name}.py" for name in (
        "__init__", "accounting", "evaluation", "ledger_validation", "market_data", "replay",
    )
)


def _git(root, *args):
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", "-C", str(root), *args],
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_ALLOW_PROTOCOL": ""},
            capture_output=True,
            check=True,
            timeout=15,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Local Git command failed: {args[0]}") from exc
    return result.stdout


def verify_engine_sources(repo_root, code_commit):
    """Return the covered source paths after a byte comparison with the commit."""
    if type(code_commit) is not str or not re.fullmatch(r"[0-9a-f]{40}", code_commit):
        raise ValueError("code_commit must be a full lowercase Git commit ID")
    root = Path(repo_root).resolve()
    top = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel").rstrip(b"\r\n")))
    if top.resolve() != root:
        raise ValueError("Expected the root of the ATAI Git checkout")
    if _git(root, "cat-file", "-t", code_commit).strip() != b"commit":
        raise ValueError("Declared Git object is not a commit")

    tree = _git(root, "ls-tree", "-z", code_commit, "--", *ENGINE_PATHS)
    blobs = {}
    for entry in tree.split(b"\0")[:-1]:
        metadata, name = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.split()
        if mode in (b"100644", b"100755") and kind == b"blob":
            blobs[name.decode("ascii")] = object_id.decode("ascii")

    for relative in ENGINE_PATHS:
        if relative not in blobs:
            raise ValueError(f"Declared commit lacks a regular source file: {relative}")
        path = root / relative
        if path.resolve() != path or not path.is_file():
            raise ValueError(f"Checkout lacks a regular source file: {relative}")
        if path.read_bytes() != _git(root, "cat-file", "blob", blobs[relative]):
            raise ValueError(f"Checkout source differs from declared commit: {relative}")

    return ENGINE_PATHS


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        code_commit = plan["spec"]["code_commit"]
        covered = verify_engine_sources(Path(__file__).resolve().parents[2], code_commit)
    except (OSError, ValueError, RuntimeError, ArithmeticError) as exc:
        parser.exit(2, f"Validation engine source check failed: {exc}\n")

    print(f"ENGINE_SOURCES_MATCH {code_commit}")
    for path in covered:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
