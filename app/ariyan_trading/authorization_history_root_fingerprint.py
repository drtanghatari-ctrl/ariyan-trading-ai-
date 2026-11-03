"""A006 B4-B2C: pure Ed25519 public-key fingerprint matching.

No root enrollment, key generation, trust establishment,
revocation, freshness, writer admission, or trading authority.
"""

import hashlib
import hmac

from .authorization_history_root_binding import (
    validate_history_root_binding,
)


def matches_history_root_fingerprint(binding, public_key):
    """Match a raw Ed25519 public key to structural binding evidence.

    A match does not establish that the binding itself is trusted.
    """
    if not validate_history_root_binding(binding):
        raise ValueError("Invalid root binding")

    if type(public_key) is not bytes or len(public_key) != 32:
        raise ValueError("Invalid Ed25519 public key")

    fingerprint = hashlib.sha256(public_key).hexdigest()

    return hmac.compare_digest(
        fingerprint,
        binding.public_key_sha256,
    )
