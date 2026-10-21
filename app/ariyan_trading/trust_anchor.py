"""A006 authenticated checkpoint primitive.

This module authenticates a journal checkpoint using HMAC-SHA-256.
It does not itself implement transaction coordination, key management,
rollback-resistant storage, or recovery authorization.
"""

import hashlib
import hmac
import json
import os
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


def read_anchor(path, key):
    with open(path, "rb") as stream:
        data = stream.read(4097)
    if len(data) > 4096:
        raise ValueError("Anchor exceeds maximum size")
    try:
        anchor = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid anchor encoding") from exc
    return verify_anchor(anchor, key)
