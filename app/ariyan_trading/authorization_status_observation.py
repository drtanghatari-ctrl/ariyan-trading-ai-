"""A006 P3C12-B6C3A: authorization status observation contract.

Structural validation only.

No independent authentication, trusted clock, durable sequence
floor, revocation proof, rollback resistance, or trading permission.
"""

from dataclasses import dataclass

from ariyan_trading.authorization_status import (
    AuthorizationStatusRecord,
    validate_authorization_status,
)
from ariyan_trading.authorization_validation import valid_name


VERSION = "ARIYAN-A006-AUTH-STATUS-OBSERVATION-V1"


@dataclass(frozen=True)
class AuthorizationStatusObservation:
    version: str
    status_record: AuthorizationStatusRecord
    source_id: str
    sequence: int
    observed_at: int
    valid_until: int


def validate_authorization_status_observation(observation):
    """Validate structure without establishing freshness or trust."""

    if type(observation) is not AuthorizationStatusObservation:
        return False

    return (
        type(observation.version) is str
        and observation.version == VERSION
        and validate_authorization_status(
            observation.status_record
        )
        and valid_name(observation.source_id)
        and type(observation.sequence) is int
        and observation.sequence >= 0
        and type(observation.observed_at) is int
        and observation.observed_at >= 0
        and type(observation.valid_until) is int
        and observation.valid_until > observation.observed_at
    )
