"""A006 P3C12-B6C3B: conservative freshness assessment.

Caller-supplied timestamps are not independently trusted.
No trusted clock, authenticated status source, rollback protection,
revocation completeness, ledger mutation, or trading permission.
"""

from ariyan_trading.authorization_status_observation import (
    validate_authorization_status_observation,
)
from ariyan_trading.authorization_status import AuthorizationStatus
from ariyan_trading.writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


def assess_authorization_freshness(*, observation, evaluation_time):
    """Assess claimed observation interval; never return ALLOW."""

    def deny(reason):
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.DENY,
            reason,
        )

    if not validate_authorization_status_observation(observation):
        return deny("Invalid authorization status observation")

    if type(evaluation_time) is not int or evaluation_time < 0:
        return deny("Invalid evaluation time")

    if not (
        observation.observed_at
        <= evaluation_time
        < observation.valid_until
    ):
        return deny("Observation outside claimed validity interval")

    status = observation.status_record.status

    if status is AuthorizationStatus.REVOKED:
        return deny("Authorization revoked")

    if status is AuthorizationStatus.SUPERSEDED:
        return deny("Authorization superseded")

    if status is AuthorizationStatus.EXPIRED:
        return deny("Authorization expired")

    if status is AuthorizationStatus.UNKNOWN:
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.UNCERTAIN,
            "Authorization status unknown",
        )

    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        "Claimed observation current; independent freshness "
        "and revocation completeness not established",
    )
