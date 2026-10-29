"""A006 P3C12-B6C2B: conservative authorization MAC verification.

Caller-supplied key bindings are NOT independently trusted.
Successful MAC verification does not grant trading permission.

No key custody, trusted provisioning, freshness verification,
revocation enforcement, ledger mutation, or trading authorization.
"""

from ariyan_trading.authorization_validation import (
    validate_authorization_evidence,
)
from ariyan_trading.authorization_key_binding import (
    validate_authorization_key_binding,
)
from ariyan_trading.authorization_mac import (
    verify_authorization_mac,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


def verify_bound_authorization(*, evidence, mac, binding):
    """Check MAC and issuer consistency; never return ALLOW."""

    def deny(reason):
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.DENY,
            reason,
        )

    if not validate_authorization_evidence(evidence):
        return deny("Invalid authorization evidence")

    if not validate_authorization_key_binding(binding):
        return deny("Invalid authorization key binding")

    if evidence.authority_id != binding.authority_id:
        return deny("Authorization authority mismatch")

    try:
        verified = verify_authorization_mac(
            evidence,
            mac,
            binding.key,
        )
    except (ValueError, TypeError):
        return deny("Invalid authorization authentication")

    if not verified:
        return deny("Authorization MAC mismatch")

    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        "MAC valid; independent authority trust not established",
    )
