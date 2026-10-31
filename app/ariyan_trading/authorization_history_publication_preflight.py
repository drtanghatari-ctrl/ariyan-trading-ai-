"""A006 C2D-04B2C1 authenticated publication preflight.

Read-only verification of publication readiness and authenticated
authorization-history evidence.

Does not establish independent freshness, rollback resistance,
writer-boundary enforcement, recovery, financial authority,
or trading authorization.
"""

from .authorization_history_publication_control import (
    verify_publication_control,
)
from .authorization_history_verifier import (
    verify_authenticated_history,
)


def verify_history_publication_preflight(
    db, stream_id, anchor, key
):
    """Verify READY state and matching authenticated history.

    Requires a caller-owned stable SQLite transaction.
    Does not acquire a writer reservation.
    """

    if not db.in_transaction:
        raise ValueError(
            "Active SQLite transaction required"
        )

    if verify_publication_control(db) != "READY":
        raise ValueError(
            "Authorization-history publication is not ready"
        )

    return verify_authenticated_history(
        db, stream_id, anchor, key
    )
