"""A006 P3C12-B6C3C1: conservative status consistency checks.

Compares caller-supplied observations only.
No authentication, durable sequence floor, trusted history,
rollback resistance, or trading authorization.
"""

from ariyan_trading.authorization_status import AuthorizationStatus
from ariyan_trading.authorization_status_observation import (
    validate_authorization_status_observation,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


TERMINAL_STATUSES = frozenset({
    AuthorizationStatus.REVOKED,
    AuthorizationStatus.SUPERSEDED,
    AuthorizationStatus.EXPIRED,
})


def assess_status_consistency(*, previous, candidate):
    """Check observation consistency; never return ALLOW."""

    def deny(reason):
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.DENY,
            reason,
        )

    if not validate_authorization_status_observation(previous):
        return deny("Invalid previous observation")

    if not validate_authorization_status_observation(candidate):
        return deny("Invalid candidate observation")

    old = previous.status_record
    new = candidate.status_record

    if old.authorization_id != new.authorization_id:
        return deny("Authorization identity changed")

    if old.authority_id != new.authority_id:
        return deny("Authority identity changed")

    if previous.source_id != candidate.source_id:
        return deny("Status source changed")

    if candidate.sequence < previous.sequence:
        return deny("Status sequence regression")

    if candidate.sequence == previous.sequence:
        if candidate != previous:
            return deny("Conflicting observations at equal sequence")

        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.UNCERTAIN,
            "Identical observation; independent trust not established",
        )

    if new.revision < old.revision:
        return deny("Authorization revision regression")

    if candidate.observed_at < previous.observed_at:
        return deny("Observation timestamp regression")

    if old.status in TERMINAL_STATUSES:
        if new.status is not old.status:
            return deny("Terminal authorization status changed")

    if new.status in TERMINAL_STATUSES:
        return deny("Candidate authorization has terminal status")

    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        "Observations structurally consistent; "
        "independent trust and rollback resistance not established",
    )
