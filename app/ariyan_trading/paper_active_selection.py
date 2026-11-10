"""Persist the authenticated paper state path and pin for restart."""

import hashlib
import hmac
import json
import os
import re
import tempfile
from pathlib import Path

from .ledger_identity import validate_ledger_identity
from .paper_execution_state import read_paper_execution_state

VERSION = "ARIYAN-A054-PAPER-ACTIVE-SELECTION-V1"
DOMAIN = VERSION.encode("ascii") + b"\x00"
MAX_BYTES = 4096


def _json(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")


def _encode(state_path, pin, ledger_identity, key):
    validate_ledger_identity(ledger_identity)
    if type(pin) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("Active selection requires a lowercase state SHA-256")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Authentication key must be at least 32 bytes")
    if type(state_path) is not str or "\x00" in state_path or not Path(state_path).is_absolute():
        raise ValueError("Active selection requires an absolute state path")
    payload = {
        "version": VERSION, "ledger_identity": ledger_identity,
        "state_path": state_path, "state_sha256": pin,
    }
    mac = hmac.new(key, DOMAIN + _json(payload), hashlib.sha256).hexdigest()
    encoded = _json({**payload, "mac": mac})
    if len(encoded) > MAX_BYTES:
        raise ValueError("Active selection exceeds maximum size")
    return encoded


def _write(fd, data):
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def create_paper_active_selection(path, state_path, *, ledger_identity,
                                  expected_state_sha256, checkpoint_key):
    """Initialize a new selector for an authenticated, independently pinned state."""
    state = Path(state_path).absolute()
    data = _encode(str(state), expected_state_sha256, ledger_identity, checkpoint_key)
    read_paper_execution_state(
        state, ledger_identity, key=checkpoint_key, expected_sha256=expected_state_sha256,
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    _write(os.open(path, flags, 0o600), data)


def read_paper_active_selection(path, ledger_identity, *, key):
    """Read one authenticated selector and return its path and pin."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Active selection exceeds maximum size")
    try:
        record = json.loads(data.decode("ascii"))
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid active selection encoding") from exc
    if type(record) is not dict or record.keys() != {
        "version", "ledger_identity", "state_path", "state_sha256", "mac",
    }:
        raise ValueError("Invalid active selection fields")
    state_path, pin = record["state_path"], record["state_sha256"]
    expected = _encode(state_path, pin, ledger_identity, key)
    if not hmac.compare_digest(data, expected):
        raise ValueError("Active selection authentication or encoding failed")
    return Path(state_path), pin


def _replace_active_selection(path, state_path, pin, ledger_identity, key):
    data = _encode(str(state_path), pin, ledger_identity, key)
    fd, temporary = tempfile.mkstemp(prefix=".atai-paper-active-", dir=path.parent)
    try:
        _write(fd, data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
