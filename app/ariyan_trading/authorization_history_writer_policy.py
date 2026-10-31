"""A006 C2D-04B2C4A authenticated history writer-policy primitive.

Pure cryptographic operations only.

No enrollment, SQLite mutation, writer-boundary enforcement,
independent freshness, rollback resistance, key custody,
financial mutation, or trading authorization.
"""

import hashlib
import hmac
import json

from .authorization_validation import valid_uuid


VERSION = "ARIYAN-A006-AUTH-HISTORY-WRITER-POLICY-V1"
DOMAIN = b"ARIYAN-A006-AUTH-HISTORY-WRITER-POLICY-V1\x00"
WRITER_MODE = "managed-v1"


def _validate_key(key):
    if type(key) is not bytes or len(key) < 32:
        raise ValueError(
            "A separately protected key of at least 32 bytes is required"
        )
    return key


def _validate_digest(value):
    if type(value) is not str or len(value) != 64:
        raise ValueError("Invalid enrollment digest")

    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Invalid enrollment digest") from exc

    if len(raw) != 32 or raw.hex() != value:
        raise ValueError("Noncanonical enrollment digest")

    return value


def _payload(stream_id, sequence, digest):
    if not valid_uuid(stream_id):
        raise ValueError("Invalid history stream ID")

    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid enrollment sequence")

    record = {
        "version": VERSION,
        "stream_id": stream_id,
        "writer_mode": WRITER_MODE,
        "enrollment_sequence": sequence,
        "enrollment_digest": _validate_digest(digest),
    }

    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return record, DOMAIN + encoded


def create_history_writer_policy(
    stream_id, sequence, digest, key
):
    record, payload = _payload(stream_id, sequence, digest)

    record["mac"] = hmac.new(
        _validate_key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return record


def verify_history_writer_policy(record, key):
    if type(record) is not dict:
        raise ValueError("Invalid history writer policy")

    expected_fields = {
        "version",
        "stream_id",
        "writer_mode",
        "enrollment_sequence",
        "enrollment_digest",
        "mac",
    }

    if set(record) != expected_fields:
        raise ValueError("Invalid history writer-policy fields")

    if record["version"] != VERSION:
        raise ValueError("Unsupported history writer-policy version")

    if record["writer_mode"] != WRITER_MODE:
        raise ValueError("Unsupported history writer mode")

    canonical, payload = _payload(
        record["stream_id"],
        record["enrollment_sequence"],
        record["enrollment_digest"],
    )

    mac = record["mac"]

    if type(mac) is not str or len(mac) != 64:
        raise ValueError("Invalid history writer-policy MAC")

    try:
        raw_mac = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid history writer-policy MAC") from exc

    if raw_mac.hex() != mac:
        raise ValueError("Noncanonical history writer-policy MAC")

    expected_mac = hmac.new(
        _validate_key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError(
            "History writer-policy authentication failed"
        )

    return canonical
