"""A006-WB02-P3C9 — Read-only verified enrollment assessment.

Verifies local enrollment evidence against a checkpointed ledger,
then performs conservative trust consistency assessment.

Does not independently authenticate trust authority responses,
establish rollback resistance, authorize writes, or trade.
"""

from ariyan_trading.enrollment_assessment import assess_enrollment
from ariyan_trading.enrollment_evidence import (
    DatabaseEvidence,
    PolicyEvidence,
    TrustEvidence,
    classify_enrollment_evidence,
)
from ariyan_trading.enrollment_verifier import verify_enrollment


def assess_verified_enrollment(
    db,
    opening_cash,
    anchor_path,
    checkpoint_key,
    policy_record,
    policy_key,
    lookup,
    *,
    publication_uncertain=False,
):
    """Verify local enrollment and conservatively assess trust.

    Requires an active, stable SQLite transaction supplied by
    the caller. Never establishes independent trust authority.
    """

    if not db.in_transaction:
        raise ValueError("Active transaction required")

    if type(publication_uncertain) is not bool:
        return classify_enrollment_evidence(
            database=DatabaseEvidence.INVALID,
            policy=PolicyEvidence.INVALID,
            trust=TrustEvidence.INVALID,
        )

    try:
        verified_policy = verify_enrollment(
            db,
            opening_cash,
            anchor_path,
            checkpoint_key,
            policy_record,
            policy_key,
        )
    except (ValueError, TypeError, OSError):
        return classify_enrollment_evidence(
            database=DatabaseEvidence.INVALID,
            policy=PolicyEvidence.INVALID,
            trust=TrustEvidence.INVALID,
        )

    return assess_enrollment(
        database=DatabaseEvidence.MANAGED,
        policy=PolicyEvidence.VERIFIED,
        lookup=lookup,
        verified_policy=verified_policy,
        publication_uncertain=publication_uncertain,
    )
