"""A006 P3C12-B1: pure writer-admission policy.

DESIGN PRIMITIVE ONLY.

Does not authenticate enrollment evidence, query an authority,
read or modify a database, or authorize actual trading.

A caller-supplied decision is not proof of enrollment status.
"""

from ariyan_trading.enrollment_state import (
    EnrollmentDecision,
    EnrollmentState,
    classify_enrollment_state,
)


def legacy_direct_write_eligible(decision):
    """Return eligibility only for a consistent LEGACY decision.

    The caller remains responsible for independently establishing
    and authenticating the enrollment state.
    """
    if type(decision) is not EnrollmentDecision:
        return False

    if type(decision.state) is not EnrollmentState:
        return False

    if type(decision.direct_writes_allowed) is not bool:
        return False

    if type(decision.enrollment_complete) is not bool:
        return False

    expected = classify_enrollment_state(decision.state)

    if decision != expected:
        return False

    return decision.state is EnrollmentState.LEGACY
