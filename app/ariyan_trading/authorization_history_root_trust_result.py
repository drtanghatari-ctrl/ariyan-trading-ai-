"""A006 B4-B3C1: human-root trust comparison result.

A MATCH is not independent authentication or authorization.
No I/O, trusted storage, key custody, freshness, revocation
enforcement, rollback resistance, or writer admission.
"""

from dataclasses import dataclass
from enum import Enum


class RootTrustComparison(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True)
class RootTrustResult:
    comparison: RootTrustComparison
    independently_authenticated: bool = False


def validate_root_trust_result(record):
    """Reject claims of independent authentication.

    This design-only contract cannot represent an authenticated
    authority decision. That requires a separate future verifier.
    """
    if type(record) is not RootTrustResult:
        return False

    if type(record.comparison) is not RootTrustComparison:
        return False

    if type(record.independently_authenticated) is not bool:
        return False

    if record.independently_authenticated:
        return False

    return True
