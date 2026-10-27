"""A006-WB02 experimental authenticated writer-policy primitive.

Pure cryptographic operations only.
Does not enroll ledgers, authorize trades, prevent rollback,
or establish secure key custody.
"""

import hashlib
import hmac
import json
import uuid

VERSION = "ARIYAN-A006-WRITER-POLICY-V1"
DOMAIN = b"ARIYAN-A006-WRITER-POLICY-V1\x00"


def _validate_identifier(value):
    if not isinstance(value, str):
        raise ValueError("Invalid ledger identifier")

    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid ledger identifier") from exc

    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Canonical UUIDv4 required")

    return value


def _validate_digest(value):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("Invalid enrollment digest")

    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Invalid enrollment digest") from exc

    if len(raw) != 32 or raw.hex() != value:
        raise ValueError("Canonical digest required")

    return value


def _validate_key(key):
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Authentication key must be at least 32 bytes")
    return key


def _payload(ledger_id, sequence, digest):
    _validate_identifier(ledger_id)
    _validate_digest(digest)

    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid enrollment sequence")

    record = {
        "version": VERSION,
        "ledger_id": ledger_id,
        "writer_mode": "managed-v1",
        "enrollment_sequence": sequence,
        "enrollment_digest": digest,
    }

    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return record, DOMAIN + encoded


def create_writer_policy(ledger_id, sequence, digest, key):
    record, payload = _payload(ledger_id, sequence, digest)

    record["mac"] = hmac.new(
        _validate_key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()

    return record


def verify_writer_policy(record, key):
    if not isinstance(record, dict):
        raise ValueError("Invalid writer policy")

    expected_fields = {
        "version",
        "ledger_id",
        "writer_mode",
        "enrollment_sequence",
        "enrollment_digest",
        "mac",
    }

    if set(record) != expected_fields:
        raise ValueError("Invalid writer-policy fields")

    if record["version"] != VERSION:
        raise ValueError("Unsupported writer-policy version")

    if record["writer_mode"] != "managed-v1":
        raise ValueError("Unsupported writer mode")

    canonical, payload = _payload(
        record["ledger_id"],
        record["enrollment_sequence"],
        record["enrollment_digest"],
    )

    mac = record["mac"]

    if not isinstance(mac, str) or len(mac) != 64:
        raise ValueError("Invalid writer-policy MAC")

    try:
        raw_mac = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid writer-policy MAC") from exc

    if raw_mac.hex() != mac:
        raise ValueError("Noncanonical writer-policy MAC")

    expected = hmac.new(
        _validate_key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, mac):
        raise ValueError("Writer-policy authentication failed")

    return canonical
