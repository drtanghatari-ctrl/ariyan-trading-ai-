"""A006 C2D read-only authenticated history verification.

Requires caller-owned stable SQLite transaction.
No persistence, recovery, freshness guarantee, or trading authority.
"""

from ariyan_trading.authorization_history_anchor import (
    verify_history_anchor,
)
from ariyan_trading.authorization_status_history_store import (
    verify_history_store,
)


def verify_authenticated_history(db, stream_id, anchor, key):
    """Compare authenticated evidence against verified stored history."""

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    anchored_stream, anchored_sequence, anchored_digest = (
        verify_history_anchor(anchor, key)
    )

    if anchored_stream != stream_id:
        raise ValueError("Authenticated history stream mismatch")

    sequence, digest = verify_history_store(db, stream_id)

    if anchored_sequence != sequence:
        raise ValueError("Authenticated history sequence mismatch")

    if anchored_digest != digest:
        raise ValueError("Authenticated history digest mismatch")

    return sequence, digest
