"""A006 P3C12-B6C3C2B: authorization-status history commitments.

Deterministic SHA-256 chain only.

No independent authentication, trusted sequence floor,
rollback resistance, persistence, or trading authorization.
"""

import hashlib

from ariyan_trading.authorization_status_history import (
    canonical_status_history_entry,
    validate_status_history_entry,
)
from ariyan_trading.authorization_validation import valid_uuid


DOMAIN = b"ARIYAN-A006-AUTH-STATUS-HISTORY-CHAIN-V1"


def _digest_bytes(digest):
    """Decode a canonical lowercase SHA-256 hexadecimal digest."""

    if type(digest) is not str or len(digest) != 64:
        raise ValueError("Invalid history digest")

    try:
        raw = bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError("Invalid history digest") from exc

    if len(raw) != 32 or raw.hex() != digest:
        raise ValueError("Noncanonical history digest")

    return raw


def opening_history_commitment(stream_id):
    """Bind the opening commitment to a valid history stream."""

    if not valid_uuid(stream_id):
        raise ValueError("Invalid history stream ID")

    return hashlib.sha256(
        DOMAIN
        + b"\x00"
        + stream_id.encode("ascii")
    ).hexdigest()


def entry_history_commitment(previous_digest, entry):
    """Commit a valid history entry to its predecessor."""

    previous = _digest_bytes(previous_digest)

    if not validate_status_history_entry(entry):
        raise ValueError("Invalid history entry")

    payload = canonical_status_history_entry(entry)

    return hashlib.sha256(
        DOMAIN
        + b"\x01"
        + previous
        + payload
    ).hexdigest()


def verify_history_chain(stream_id, entries, expected_digest):
    """Verify a complete ordered history against an expected digest.

    The expected digest is caller-supplied. This function does not
    establish that the digest came from a trusted authority.
    """

    _digest_bytes(expected_digest)

    if type(entries) not in (list, tuple):
        raise ValueError("History entries must be a list or tuple")

    digest = opening_history_commitment(stream_id)

    for expected_sequence, entry in enumerate(entries, start=1):
        if not validate_status_history_entry(entry):
            raise ValueError("Invalid history entry")

        if entry.stream_id != stream_id:
            raise ValueError("History stream mismatch")

        if entry.history_sequence != expected_sequence:
            raise ValueError("History sequence discontinuity")

        digest = entry_history_commitment(digest, entry)

    if digest != expected_digest:
        raise ValueError("History commitment mismatch")

    return digest
