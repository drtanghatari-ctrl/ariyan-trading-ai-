"""A006 B4-B3C2: conservative human-root evidence evaluation.

Pure comparison of caller-supplied evidence and external pins.
No independent trust authentication, current-status verification,
freshness, rollback resistance, writer admission, or trading.
"""

from .authorization_history_root_enrollment import (
    validate_history_root_enrollment,
)
from .authorization_history_root_provenance import (
    validate_history_root_provenance,
)
from .authorization_history_root_anchor_match import (
    matches_external_root_anchor,
)
from .authorization_history_root_trust_result import (
    RootTrustComparison,
    RootTrustResult,
)
from .authorization_status import AuthorizationStatus


def evaluate_history_root_evidence(
    enrollment,
    provenance,
    root_authority_id,
    public_key_sha256,
):
    """Evaluate structural consistency without granting authority."""

    def result(comparison):
        return RootTrustResult(
            comparison=comparison,
            independently_authenticated=False,
        )

    if (
        not validate_history_root_enrollment(enrollment)
        or not validate_history_root_provenance(provenance)
    ):
        return result(RootTrustComparison.INVALID)

    if (
        enrollment.status is not AuthorizationStatus.ACTIVE
        or provenance.status is not AuthorizationStatus.ACTIVE
    ):
        return result(RootTrustComparison.INVALID)

    if (
        enrollment.binding != provenance.binding
        or enrollment.lifecycle_revision
        != provenance.lifecycle_revision
    ):
        return result(RootTrustComparison.MISMATCH)

    if root_authority_id is None or public_key_sha256 is None:
        return result(RootTrustComparison.UNAVAILABLE)

    try:
        matched = matches_external_root_anchor(
            enrollment,
            root_authority_id,
            public_key_sha256,
        )
    except (ValueError, TypeError):
        return result(RootTrustComparison.INVALID)

    if not matched:
        return result(RootTrustComparison.MISMATCH)

    return result(RootTrustComparison.MATCH)
