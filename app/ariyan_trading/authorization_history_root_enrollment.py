"""A006 B4-B3A: structural human-root enrollment lifecycle.

Design-only evidence. No enrollment issuance, authentication,
trusted storage, revocation enforcement, freshness, rollback
resistance, writer admission, or trading authorization.
"""

from dataclasses import dataclass

from .authorization_history_root_binding import (
    HistoryRootBinding,
    validate_history_root_binding,
)
from .authorization_status import AuthorizationStatus


VERSION = "ARIYAN-A006-HISTORY-ROOT-ENROLLMENT-V1"


@dataclass(frozen=True)
class HistoryRootEnrollment:
    version: str
    binding: HistoryRootBinding
    status: AuthorizationStatus
    lifecycle_revision: int


def validate_history_root_enrollment(record):
    """Validate evidence structure, not independent trust."""

    if type(record) is not HistoryRootEnrollment:
        return False

    if type(record.version) is not str or record.version != VERSION:
        return False

    if not validate_history_root_binding(record.binding):
        return False

    if type(record.status) is not AuthorizationStatus:
        return False

    if (
        type(record.lifecycle_revision) is not int
        or record.lifecycle_revision <= 0
    ):
        return False

    if record.lifecycle_revision < record.binding.enrollment_revision:
        return False

    return True
