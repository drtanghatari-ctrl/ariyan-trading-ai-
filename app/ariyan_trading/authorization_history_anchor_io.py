"""A006 C2D-04A authorization-history anchor filesystem I/O.

Atomic replacement with file and directory synchronization.

No SQLite coordination, independent freshness, rollback resistance,
automatic recovery, or trading authority.

A failed write may leave the publication outcome uncertain.
"""

import json
import os
import tempfile
from pathlib import Path

from ariyan_trading.authorization_history_anchor import (
    verify_history_anchor,
)

MAX_ANCHOR_BYTES = 4096


def write_history_anchor(path, anchor, key):
    """Publish authenticated history evidence using atomic replacement.

    Successful return requires file and directory synchronization.
    An exception after replacement does not prove the old file survived.
    """
    verify_history_anchor(anchor, key)

    path = Path(path)

    if not path.parent.is_dir():
        raise FileNotFoundError(
            "History anchor directory does not exist"
        )

    data = json.dumps(
        anchor,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    if len(data) > MAX_ANCHOR_BYTES:
        raise ValueError("History anchor exceeds maximum size")

    fd, temporary = tempfile.mkstemp(
        prefix=".ariyan-history-anchor-",
        dir=str(path.parent),
    )

    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

        os.replace(temporary, path)

        flags = os.O_RDONLY

        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY

        directory_fd = os.open(str(path.parent), flags)

        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_history_anchor(path, key):
    """Read bounded, authenticated history evidence from disk."""
    with open(path, "rb") as stream:
        data = stream.read(MAX_ANCHOR_BYTES + 1)

    if len(data) > MAX_ANCHOR_BYTES:
        raise ValueError("History anchor exceeds maximum size")

    try:
        anchor = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError(
            "Invalid history anchor encoding"
        ) from exc

    return verify_history_anchor(anchor, key)
