"""A006 P3C12-B3: fail-closed writer authorization decision model.

DESIGN PRIMITIVE ONLY.

No independently authenticated writer authority exists in this module.
No database, network, cryptographic, or trading operations occur here.

ALLOW is reserved for a future authenticated authorization boundary.
Caller-supplied enrollment decisions and trust assertions cannot
establish authorization.
"""

from dataclasses import dataclass
from enum import Enum


class WriterAuthorizationStatus(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class WriterAuthorizationDecision:
    status: WriterAuthorizationStatus
    reason: str


def assess_writer_authorization(
    *,
    operation,
    enrollment_decision=None,
    trust_lookup=None,
):
    """Conservatively classify a proposed writer operation.

    This function cannot authorize an operation.
    It does not authenticate its inputs.
    """

    if type(operation) is not str or operation not in (
        "BUY",
        "SELL",
    ):
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.DENY,
            "Unsupported writer operation",
        )

    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        "Independent writer authorization is not established",
    )
