"""A006-WB02-P3C8 — Conservative enrollment assessment.

Pure read-only assessment of caller-supplied evidence.

No independent authority authentication, I/O, enrollment,
rollback protection, or trading authorization is provided.

In particular, a TrustLookup.authenticated flag does not
establish independent authority.
"""

from ariyan_trading.enrollment_evidence import (
    DatabaseEvidence,
    PolicyEvidence,
    TrustEvidence,
    classify_enrollment_evidence,
)
from ariyan_trading.enrollment_state import EnrollmentState
from ariyan_trading.trust_authority import (
    TrustLookupStatus,
    classify_trust_lookup,
)
from ariyan_trading.trust_consistency import (
    trust_record_matches_policy,
)


def assess_enrollment(
    *,
    database,
    policy,
    lookup,
    verified_policy=None,
    publication_uncertain=False,
):
    """Assess evidence without claiming independent authority."""

    if (
        not isinstance(database, DatabaseEvidence)
        or not isinstance(policy, PolicyEvidence)
        or type(publication_uncertain) is not bool
    ):
        return classify_enrollment_evidence(
            database=DatabaseEvidence.INVALID,
            policy=PolicyEvidence.INVALID,
            trust=TrustEvidence.INVALID,
        )

    status = classify_trust_lookup(lookup)

    if status is TrustLookupStatus.INVALID:
        trust = TrustEvidence.INVALID

    elif status is TrustLookupStatus.UNAVAILABLE:
        trust = TrustEvidence.UNAVAILABLE

    elif status is TrustLookupStatus.ABSENT:
        trust = TrustEvidence.ABSENT

    elif status is TrustLookupStatus.PRESENT:
        if policy is PolicyEvidence.VERIFIED:
            if not trust_record_matches_policy(
                lookup.record, verified_policy
            ):
                trust = TrustEvidence.INVALID
            else:
                trust = TrustEvidence.ENROLLED
        else:
            trust = TrustEvidence.ENROLLED

    else:
        trust = TrustEvidence.INVALID

    # No independent authority has been established.
    # Never promote caller assertions to authoritative evidence.
    return classify_enrollment_evidence(
        database=database,
        policy=policy,
        trust=trust,
        trust_authoritative=False,
        publication_uncertain=publication_uncertain,
    )
