"""A006 P3C12-B6B: conservative authorization assessment.

Pure design primitive.

No independent authentication, freshness verification,
rollback resistance, ledger mutation, or trading permission.

This module cannot return ALLOW.
"""

from ariyan_trading.authorization_validation import (
    validate_authorization_evidence,
)
from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    validate_authorization_status,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


def _deny(reason):
    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.DENY,
        reason,
    )


def _uncertain(reason):
    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        reason,
    )


def assess_authorization(
    *,
    evidence,
    status_record,
    operation,
):
    """Assess structural consistency without granting permission."""

    if type(operation) is not str or operation not in (
        "BUY",
        "SELL",
    ):
        return _deny("Unsupported operation")

    if not validate_authorization_evidence(evidence):
        return _deny("Invalid authorization evidence")

    if not validate_authorization_status(status_record):
        return _deny("Invalid authorization status record")

    if status_record.authorization_id != evidence.authorization_id:
        return _deny("Authorization identity mismatch")

    if status_record.authority_id != evidence.authority_id:
        return _deny("Authority identity mismatch")

    if status_record.revision != evidence.revision:
        return _deny("Authorization revision mismatch")

    if operation not in evidence.allowed_operations:
        return _deny("Operation not permitted by evidence")

    if status_record.status is AuthorizationStatus.REVOKED:
        return _deny("Authorization revoked")

    if status_record.status is AuthorizationStatus.SUPERSEDED:
        return _deny("Authorization superseded")

    if status_record.status is AuthorizationStatus.EXPIRED:
        return _deny("Authorization expired")

    if status_record.status is AuthorizationStatus.UNKNOWN:
        return _uncertain("Authorization status unknown")

    return _uncertain(
        "Independent authorization trust not established"
    )
