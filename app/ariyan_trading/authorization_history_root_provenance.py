"""A006 B4-B3B2: external human-root provenance contract.

Structural evidence only. No independently authenticated trust,
key custody, enrollment issuance, revocation enforcement,
freshness, rollback resistance, writer admission, or trading.
"""

from dataclasses import dataclass

from .authorization_history_root_binding import (
    HistoryRootBinding,
    validate_history_root_binding,
)
from .authorization_status import AuthorizationStatus
from .authorization_validation import valid_name


VERSION = "ARIYAN-A006-HISTORY-ROOT-PROVENANCE-V1"


@dataclass(frozen=True)
class HistoryRootProvenance:
    version: str
    binding: HistoryRootBinding
    lifecycle_revision: int
    status: AuthorizationStatus
    provenance_reference: str


def validate_history_root_provenance(record):
    """Validate provenance structure, never its authenticity."""

    if type(record) is not HistoryRootProvenance:
        return False

    if type(record.version) is not str or record.version != VERSION:
        return False

    if not validate_history_root_binding(record.binding):
        return False

    if (
        type(record.lifecycle_revision) is not int
        or record.lifecycle_revision <= 0
        or record.lifecycle_revision
        < record.binding.enrollment_revision
    ):
        return False

    if type(record.status) is not AuthorizationStatus:
        return False

    if not valid_name(record.provenance_reference):
        return False

    return True
