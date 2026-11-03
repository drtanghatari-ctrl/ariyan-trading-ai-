"""A006 C2D-04B2C4B4-B1: experimental delegation MAC.

Canonical HMAC-SHA-256 authentication only.
No independent human-root identity, key custody, freshness,
revocation, writer admission, SQLite writes, or trading authority.
"""

import hashlib
import hmac
import json

from .authorization_history_writer_authority import (
    validate_history_writer_authority_evidence,
)


VERSION = "ARIYAN-A006-HISTORY-WRITER-AUTHORITY-MAC-V1"
DOMAIN = b"ARIYAN-A006-HISTORY-WRITER-AUTHORITY-MAC-V1\x00"


def _validate_key(key):
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("Invalid delegation MAC key")
    return key


def canonical_history_writer_authority_payload(evidence):
    """Canonical bytes; does not establish authority."""

    if not validate_history_writer_authority_evidence(evidence):
        raise ValueError("Invalid writer authority evidence")

    record = {
        "version": VERSION,
        "evidence_version": evidence.version,
        "authorization_id": evidence.authorization_id,
        "root_authority_id": evidence.root_authority_id,
        "writer_id": evidence.writer_id,
        "stream_id": evidence.stream_id,
        "revision": evidence.revision,
        "allowed_operations": sorted(evidence.allowed_operations),
        "valid_from": evidence.valid_from,
        "valid_until": evidence.valid_until,
        "status_reference": evidence.status_reference,
    }

    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return DOMAIN + encoded


def create_history_writer_authority_mac(evidence, key):
    """Create an authentication tag, not a permission."""

    payload = canonical_history_writer_authority_payload(evidence)

    return hmac.new(
        _validate_key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()


def verify_history_writer_authority_mac(evidence, mac, key):
    """Verify authentication; never authorize history writes."""

    if type(mac) is not str or len(mac) != 64:
        raise ValueError("Invalid delegation MAC")

    try:
        raw = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid delegation MAC") from exc

    if len(raw) != 32 or raw.hex() != mac:
        raise ValueError("Noncanonical delegation MAC")

    expected = create_history_writer_authority_mac(evidence, key)

    return hmac.compare_digest(expected, mac)
