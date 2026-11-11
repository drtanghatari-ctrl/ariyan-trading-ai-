"""A006 authenticated checkpoint primitive.

This module authenticates a journal checkpoint using HMAC-SHA-256.
It does not itself implement transaction coordination, key management,
rollback-resistant storage, or recovery authorization.
"""

import hashlib
import hmac
import json
import os
import stat
import tempfile
from pathlib import Path

VERSION = "ARIYAN-A006-ANCHOR-V1"


def _digest(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("Invalid journal digest")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Invalid journal digest") from exc
    if len(raw) != 32:
        raise ValueError("Invalid journal digest")
    return raw.hex()


def _payload(sequence, digest):
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid journal sequence")
    obj = {
        "version": VERSION,
        "sequence": sequence,
        "digest": _digest(digest),
    }
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _key(key):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("A separately protected key of at least 32 bytes is required")
    return key


def create_anchor(sequence, digest, key):
    payload = _payload(sequence, digest)
    mac = hmac.new(_key(key), payload, hashlib.sha256).hexdigest()
    return {
        "version": VERSION,
        "sequence": sequence,
        "digest": _digest(digest),
        "mac": mac,
    }


def verify_anchor(anchor, key):
    if not isinstance(anchor, dict):
        raise ValueError("Invalid anchor")
    if set(anchor) != {"version", "sequence", "digest", "mac"}:
        raise ValueError("Invalid anchor fields")
    if anchor["version"] != VERSION:
        raise ValueError("Unsupported anchor version")

    payload = _payload(anchor["sequence"], anchor["digest"])
    mac = anchor["mac"]
    if not isinstance(mac, str) or len(mac) != 64:
        raise ValueError("Invalid anchor MAC")
    try:
        bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid anchor MAC") from exc

    expected = hmac.new(_key(key), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        raise ValueError("Anchor authentication failed")
    return anchor["sequence"], anchor["digest"]


def write_anchor(path, anchor, key):
    """Write a verified anchor with atomic replacement and file fsync."""
    verify_anchor(anchor, key)
    path = Path(path)
    if not path.parent.is_dir():
        raise FileNotFoundError("Anchor directory does not exist")

    data = json.dumps(
        anchor, sort_keys=True, separators=(",", ":")
    ).encode("ascii")

    fd, temporary = tempfile.mkstemp(
        prefix=".ariyan-anchor-", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

        _sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_anchor(path, key):
    with open(path, "rb") as stream:
        return _read_anchor_stream(stream, key)


def _read_anchor_stream(stream, key):
    data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("Anchor exceeds maximum size")
    try:
        anchor = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid anchor encoding") from exc
    return verify_anchor(anchor, key)


def _sync_directory(path):
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def sync_verified_anchor(path, key, expected_tip):
    """Authenticate and sync the existing anchor and its directory entry."""
    path = Path(path)
    directory = path.parent.stat()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _read_anchor_stream(stream, key) != expected_tip:
            raise ValueError("Anchor differs from the expected checkpoint before sync")
        os.fsync(stream.fileno())
        _sync_directory(path.parent)
        if (
            not os.path.samestat(opened, path.lstat())
            or not os.path.samestat(directory, path.parent.stat())
        ):
            raise ValueError("Anchor path changed during sync")
