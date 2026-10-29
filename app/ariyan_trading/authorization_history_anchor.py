"""A006 C2D: authorization-history checkpoint authentication.

Pure HMAC-SHA-256 authentication only.

No persistence, freshness guarantee, rollback-resistant storage,
automatic recovery, financial mutation, or trading authorization.
"""

import hashlib
import hmac
import json

from ariyan_trading.authorization_validation import valid_uuid

VERSION = "ARIYAN-A006-AUTH-HISTORY-ANCHOR-V1"
DOMAIN = b"ARIYAN-A006-AUTH-HISTORY-ANCHOR-V1\x00"


def _key(key):
    if type(key) is not bytes or len(key) < 32:
        raise ValueError(
            "A separately protected key of at least 32 bytes is required"
        )
    return key


def _digest(value):
    if type(value) is not str or len(value) != 64:
        raise ValueError("Invalid history digest")

    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("Invalid history digest") from exc

    if len(raw) != 32 or raw.hex() != value:
        raise ValueError("Noncanonical history digest")

    return value


def _payload(stream_id, sequence, digest):
    if not valid_uuid(stream_id):
        raise ValueError("Invalid history stream ID")

    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid history sequence")

    obj = {
        "version": VERSION,
        "stream_id": stream_id,
        "history_sequence": sequence,
        "history_digest": _digest(digest),
    }

    encoded = json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return DOMAIN + encoded


def create_history_anchor(stream_id, sequence, digest, key):
    payload = _payload(stream_id, sequence, digest)
    mac = hmac.new(_key(key), payload, hashlib.sha256).hexdigest()

    return {
        "version": VERSION,
        "stream_id": stream_id,
        "history_sequence": sequence,
        "history_digest": _digest(digest),
        "mac": mac,
    }


def verify_history_anchor(anchor, key):
    if type(anchor) is not dict:
        raise ValueError("Invalid history anchor")

    expected_fields = {
        "version",
        "stream_id",
        "history_sequence",
        "history_digest",
        "mac",
    }

    if set(anchor) != expected_fields:
        raise ValueError("Invalid history anchor fields")

    if anchor["version"] != VERSION:
        raise ValueError("Unsupported history anchor version")

    payload = _payload(
        anchor["stream_id"],
        anchor["history_sequence"],
        anchor["history_digest"],
    )

    mac = anchor["mac"]

    if type(mac) is not str or len(mac) != 64:
        raise ValueError("Invalid history anchor MAC")

    try:
        raw_mac = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid history anchor MAC") from exc

    if raw_mac.hex() != mac:
        raise ValueError("Noncanonical history anchor MAC")

    expected_mac = hmac.new(
        _key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_mac, mac):
        raise ValueError("History anchor authentication failed")

    return (
        anchor["stream_id"],
        anchor["history_sequence"],
        anchor["history_digest"],
    )
