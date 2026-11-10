"""Create and verify an authenticated state file for offline paper orders."""

import hashlib
import hmac
import json
import os
import re
from pathlib import Path

from .ledger_identity import validate_ledger_identity

PAPER_EXECUTION_STATES = ("NORMAL", "STOP", "FREEZE")
VERSION = "ARIYAN-A050-PAPER-EXECUTION-STATE-V1"
DOMAIN = VERSION.encode("ascii") + b"\x00"
MAX_STATE_BYTES = 4096


def _encode(record):
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("ascii")


def _authenticated_record(ledger_identity, execution_state, key):
    validate_ledger_identity(ledger_identity)
    if type(execution_state) is not str or execution_state not in PAPER_EXECUTION_STATES:
        raise ValueError("Unsupported paper execution state")
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Authentication key must be at least 32 bytes")
    payload = {
        "version": VERSION, "ledger_identity": ledger_identity,
        "execution_state": execution_state,
    }
    mac = hmac.new(key, DOMAIN + _encode(payload), hashlib.sha256).hexdigest()
    return {**payload, "mac": mac}


def create_paper_execution_state(path, ledger_identity, execution_state, *, key):
    """Create a state file exclusively and synchronize its contents."""
    create_pinned_paper_execution_state(path, ledger_identity, execution_state, key=key)


def create_pinned_paper_execution_state(path, ledger_identity, execution_state, *, key):
    """Create the file exclusively and return the hash of the bytes written."""
    data = _encode(_authenticated_record(ledger_identity, execution_state, key))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(data).hexdigest()


def read_paper_execution_state(path, ledger_identity, *, key, expected_sha256=None):
    """Verify the state record and, when supplied, its independently retained hash."""
    if expected_sha256 is not None and (
        type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
    ):
        raise ValueError("Expected paper execution state SHA-256 must be lowercase hex")
    validate_ledger_identity(ledger_identity)
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_STATE_BYTES + 1)
    if len(data) > MAX_STATE_BYTES:
        raise ValueError("Paper execution state exceeds maximum size")
    if expected_sha256 is not None and not hmac.compare_digest(
        hashlib.sha256(data).hexdigest(), expected_sha256,
    ):
        raise ValueError("Paper execution state differs from the expected SHA-256")
    try:
        record = json.loads(data.decode("ascii"))
    except (ValueError, RecursionError) as exc:
        raise ValueError("Invalid paper execution state encoding") from exc

    if type(record) is not dict or record.keys() != {
        "version", "ledger_identity", "execution_state", "mac",
    }:
        raise ValueError("Invalid paper execution state fields")
    if record["version"] != VERSION or record["ledger_identity"] != ledger_identity:
        raise ValueError("Paper execution state version or ledger identity mismatch")

    state = record["execution_state"]
    expected = _encode(_authenticated_record(ledger_identity, state, key))
    if not hmac.compare_digest(data, expected):
        raise ValueError("Paper execution state authentication or encoding failed")
    return state
