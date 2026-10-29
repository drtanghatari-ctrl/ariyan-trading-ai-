"""A006 B5: experimental authorization-evidence MAC.

Authenticates bytes only. Does not grant trading authority.
"""

import hashlib
import hmac

from ariyan_trading.authorization_payload import (
    canonical_authorization_payload,
)


def _key(key):
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("Invalid authorization MAC key")
    return key


def create_authorization_mac(evidence, key):
    """Return a canonical lowercase HMAC-SHA-256 tag."""

    payload = canonical_authorization_payload(evidence)

    return hmac.new(
        _key(key),
        payload,
        hashlib.sha256,
    ).hexdigest()


def verify_authorization_mac(evidence, mac, key):
    """Verify evidence authentication; never authorize trades."""

    if type(mac) is not str or len(mac) != 64:
        raise ValueError("Invalid authorization MAC")

    try:
        raw = bytes.fromhex(mac)
    except ValueError as exc:
        raise ValueError("Invalid authorization MAC") from exc

    if len(raw) != 32 or raw.hex() != mac:
        raise ValueError("Noncanonical authorization MAC")

    expected = create_authorization_mac(evidence, key)

    return hmac.compare_digest(expected, mac)
