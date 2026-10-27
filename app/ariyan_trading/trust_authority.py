"""A006-WB02-P3C4 — Pure trust-authority interface.

DESIGN MODEL ONLY.

No storage, cryptography, networking, ledger mutation,
or trading authorization is implemented.

A lookup outcome supplied to this module is not independently
verified by this module.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class TrustLookupStatus(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True)
class TrustRecord:
    ledger_id: str
    enrollment_sequence: int
    enrollment_digest: str
    writer_policy_version: str
    authority_id: str
    revision: int
    record_version: str


@dataclass(frozen=True)
class TrustLookup:
    status: TrustLookupStatus
    record: TrustRecord | None = None
    history_complete: bool = False
    authenticated: bool = False


class TrustAuthorityReader(Protocol):
    """Interface for a future independent authority."""

    def lookup(self, ledger_id: str) -> TrustLookup:
        ...


def classify_trust_lookup(lookup: TrustLookup) -> TrustLookupStatus:
    """Validate outcome consistency, not authenticity.

    A caller-provided authenticated=True flag is only an
    assertion. It is not cryptographic verification.
    """

    if not isinstance(lookup, TrustLookup):
        return TrustLookupStatus.INVALID

    if (
        not isinstance(lookup.status, TrustLookupStatus)
        or type(lookup.history_complete) is not bool
        or type(lookup.authenticated) is not bool
    ):
        return TrustLookupStatus.INVALID

    if lookup.status is TrustLookupStatus.PRESENT:
        if (
            not isinstance(lookup.record, TrustRecord)
            or not lookup.authenticated
        ):
            return TrustLookupStatus.INVALID

        return TrustLookupStatus.PRESENT

    if lookup.status is TrustLookupStatus.ABSENT:
        if (
            lookup.record is not None
            or not lookup.history_complete
            or not lookup.authenticated
        ):
            return TrustLookupStatus.INVALID

        return TrustLookupStatus.ABSENT

    if lookup.status is TrustLookupStatus.UNAVAILABLE:
        if (
            lookup.record is not None
            or lookup.authenticated
            or lookup.history_complete
        ):
            return TrustLookupStatus.INVALID

        return TrustLookupStatus.UNAVAILABLE

    if lookup.status is TrustLookupStatus.INVALID:
        return TrustLookupStatus.INVALID

    return TrustLookupStatus.INVALID
