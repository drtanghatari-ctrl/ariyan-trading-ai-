"""A006 B4-B2A: verification-only Ed25519 delegation primitive.

No key generation, signing, trust enrollment, freshness,
revocation, writer admission, SQLite mutation or trading authority.

The caller-supplied public key is NOT trusted by this module.
"""

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PublicKey,
)

from .authorization_history_writer_authority_mac import (
    canonical_history_writer_authority_payload,
)


PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


def verify_history_writer_root_signature(
    evidence,
    signature,
    public_key,
):
    """Verify signature mathematics only; never grant authority."""

    payload = canonical_history_writer_authority_payload(evidence)

    if type(signature) is not bytes or len(signature) != SIGNATURE_BYTES:
        raise ValueError("Invalid Ed25519 signature encoding")

    if type(public_key) is not bytes or len(public_key) != PUBLIC_KEY_BYTES:
        raise ValueError("Invalid Ed25519 public-key encoding")

    verifier = Ed25519PublicKey.from_public_bytes(public_key)

    try:
        verifier.verify(signature, payload)
    except InvalidSignature:
        return False

    return True
