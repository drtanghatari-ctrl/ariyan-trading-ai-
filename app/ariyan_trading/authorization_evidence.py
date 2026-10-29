"""A006 P3C12-B4: structural authorization evidence contract.

DESIGN MODEL ONLY.

No authentication, freshness verification, revocation lookup,
ledger mutation, or trading authorization is implemented.
"""

from dataclasses import dataclass


AUTHORIZATION_EVIDENCE_VERSION = (
    "ARIYAN-A006-AUTHORIZATION-EVIDENCE-V1"
)


@dataclass(frozen=True)
class AuthorizationEvidence:
    version: str
    authorization_id: str
    ledger_id: str
    writer_id: str
    authority_id: str
    revision: int
    allowed_operations: tuple[str, ...]
    valid_from: int
    valid_until: int
