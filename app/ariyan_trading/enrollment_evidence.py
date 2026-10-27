"""A006-WB02-P3C2 pure enrollment evidence classification.

No I/O, cryptographic verification, publication, recovery,
or trading authorization.

All supplied evidence must be independently established.
"""

from dataclasses import dataclass
from enum import Enum

from .enrollment_state import EnrollmentState


class DatabaseEvidence(str, Enum):
    ABSENT = "absent"
    PREPARING = "preparing"
    MANAGED = "managed"
    INVALID = "invalid"


class PolicyEvidence(str, Enum):
    ABSENT = "absent"
    VERIFIED = "verified"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


class TrustEvidence(str, Enum):
    ABSENT = "absent"
    ENROLLED = "enrolled"
    INVALID = "invalid"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class EnrollmentEvidenceDecision:
    state: EnrollmentState
    reason: str
    enrollment_verified: bool


def classify_enrollment_evidence(
    *,
    database,
    policy,
    trust,
    trust_authoritative=False,
    publication_uncertain=False,
):
    """Classify independently established enrollment evidence.

    VERIFIED policy means authentication, ledger identity,
    historical commitment, and current checkpoint have
    already been verified by the caller.

    ENROLLED trust means independently authenticated evidence
    bound to the same ledger and enrollment.

    ABSENT trust means an authoritative lookup found no record,
    not that the registry could not be contacted.

    This function does not perform those checks itself.
    """

    def decision(state, reason):
        return EnrollmentEvidenceDecision(
            state=state,
            reason=reason,
            enrollment_verified=(state is EnrollmentState.MANAGED),
        )

    if (
        not isinstance(database, DatabaseEvidence)
        or not isinstance(policy, PolicyEvidence)
        or not isinstance(trust, TrustEvidence)
        or type(trust_authoritative) is not bool
        or type(publication_uncertain) is not bool
    ):
        return decision(
            EnrollmentState.INVALID,
            "Invalid enrollment evidence input",
        )

    if (
        database is DatabaseEvidence.INVALID
        or policy is PolicyEvidence.INVALID
        or trust is TrustEvidence.INVALID
    ):
        return decision(
            EnrollmentState.INVALID,
            "Enrollment evidence is invalid",
        )

    if publication_uncertain:
        return decision(
            EnrollmentState.UNCERTAIN,
            "Enrollment publication outcome is uncertain",
        )

    if not trust_authoritative:
        return decision(
            EnrollmentState.UNCERTAIN,
            "Independent trust authority is not established",
        )

    if trust is TrustEvidence.UNAVAILABLE:
        return decision(
            EnrollmentState.UNCERTAIN,
            "Independent trust evidence is unavailable",
        )

    if policy is PolicyEvidence.UNAVAILABLE:
        return decision(
            EnrollmentState.UNCERTAIN,
            "Policy evidence is unavailable",
        )

    if trust is TrustEvidence.ABSENT:
        if (
            database is DatabaseEvidence.ABSENT
            and policy is PolicyEvidence.ABSENT
        ):
            return decision(
                EnrollmentState.LEGACY,
                "Authoritative trust registry reports no enrollment",
            )

        return decision(
            EnrollmentState.INVALID,
            "Local enrollment evidence conflicts with trust registry",
        )

    if trust is TrustEvidence.ENROLLED:
        if (
            database is DatabaseEvidence.MANAGED
            and policy is PolicyEvidence.VERIFIED
        ):
            return decision(
                EnrollmentState.MANAGED,
                "Authenticated enrollment evidence is consistent",
            )

        if database is DatabaseEvidence.PREPARING:
            return decision(
                EnrollmentState.PREPARING,
                "Enrollment preparation is recorded but incomplete",
            )

        return decision(
            EnrollmentState.INVALID,
            "Trusted enrollment conflicts with local evidence",
        )

    return decision(
        EnrollmentState.INVALID,
        "Unrecognized enrollment evidence combination",
    )
