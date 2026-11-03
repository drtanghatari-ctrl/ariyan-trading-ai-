"""A006 C2D-04B2C4B3: conservative history-writer assessment.

Pure design primitive. No ALLOW decision is possible.

Caller-supplied enrollment classifications and authority status
are not independently authenticated. This module does not enforce
a database boundary or authorize financial operations.
"""

from enum import Enum

from .authorization_status import AuthorizationStatus
from .writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


class HistoryEnrollmentState(str, Enum):
    INVALID = "invalid"
    UNKNOWN = "unknown"
    AUTHENTICATED = "authenticated"


def assess_history_writer_admission(
    *,
    operation,
    enrollment_state=HistoryEnrollmentState.UNKNOWN,
    authority_status=AuthorizationStatus.UNKNOWN,
):
    """Classify a proposed history write without granting permission."""

    def decision(status, reason):
        return WriterAuthorizationDecision(status, reason)

    deny = WriterAuthorizationStatus.DENY
    uncertain = WriterAuthorizationStatus.UNCERTAIN

    if type(operation) is not str or operation != "APPEND_HISTORY":
        return decision(deny, "Unsupported history operation")

    if type(enrollment_state) is not HistoryEnrollmentState:
        return decision(deny, "Invalid enrollment classification")

    if type(authority_status) is not AuthorizationStatus:
        return decision(deny, "Invalid authority status")

    if enrollment_state is HistoryEnrollmentState.INVALID:
        return decision(deny, "Invalid writer enrollment")

    if authority_status in (
        AuthorizationStatus.REVOKED,
        AuthorizationStatus.SUPERSEDED,
        AuthorizationStatus.EXPIRED,
    ):
        return decision(deny, "Authority has terminal status")

    if enrollment_state is HistoryEnrollmentState.UNKNOWN:
        return decision(uncertain, "Writer enrollment not established")

    if authority_status is AuthorizationStatus.UNKNOWN:
        return decision(uncertain, "Current authority not established")

    return decision(
        uncertain,
        "Caller classifications cannot establish independent authority",
    )
