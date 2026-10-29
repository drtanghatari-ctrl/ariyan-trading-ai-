"""A006 P3C12-B6-A: authorization status design contract.

Pure structural model only.

No authentication, independent authority lookup,
freshness verification, rollback resistance,
ledger mutation, or trading authorization.
"""

from dataclasses import dataclass
from enum import Enum


class AuthorizationStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class AuthorizationStatusRecord:
    authorization_id: str
    authority_id: str
    revision: int
    status: AuthorizationStatus


def validate_authorization_status(record):
    """Validate structure only; never establish authority."""

    from ariyan_trading.authorization_validation import (
        valid_uuid,
        valid_name,
    )

    if type(record) is not AuthorizationStatusRecord:
        return False

    if not valid_uuid(record.authorization_id):
        return False

    if not valid_name(record.authority_id):
        return False

    if type(record.revision) is not int or record.revision <= 0:
        return False

    if type(record.status) is not AuthorizationStatus:
        return False

    return True
