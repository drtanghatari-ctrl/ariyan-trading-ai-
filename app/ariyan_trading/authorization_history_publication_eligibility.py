"""A006 C2D-04B2C3A publication eligibility verification.

Read-only checks of pending history and its authenticated predecessor.

No publication, recovery, independent freshness, rollback resistance,
financial mutation, or trading authorization.
"""

from .authorization_history_anchor import (
    verify_history_anchor,
)
from .authorization_history_anchor_io import (
    read_history_anchor,
)
from .authorization_history_publication_store import (
    verify_pending_publication_intent,
)
from .authorization_status_history_commitment import (
    opening_history_commitment,
)


def verify_history_publication_eligibility(
    db, stream_id, predecessor_anchor, anchor_path, key
):
    """Verify that a pending history tip has the expected predecessor.

    Requires a caller-owned stable SQLite transaction.

    The caller must establish the trustworthiness of the supplied
    predecessor anchor independently. This function does not establish
    freshness or prevent rollback of a matching database/anchor pair.

    The on-disk anchor must already exist and match the predecessor.
    """

    if not db.in_transaction:
        raise ValueError(
            "Active SQLite transaction required"
        )

    intent = verify_pending_publication_intent(
        db, stream_id
    )

    sequence = intent["history_sequence"]

    if sequence < 1:
        raise ValueError(
            "Pending publication has no history entry"
        )

    predecessor = verify_history_anchor(
        predecessor_anchor, key
    )

    if predecessor[0] != stream_id:
        raise ValueError(
            "Predecessor anchor stream mismatch"
        )

    if predecessor[1] != sequence - 1:
        raise ValueError(
            "Predecessor anchor sequence mismatch"
        )

    if sequence == 1:
        expected_digest = opening_history_commitment(
            stream_id
        )
    else:
        row = db.execute(
            "SELECT digest "
            "FROM authorization_history_commitments "
            "WHERE history_sequence=?",
            (sequence - 1,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "Missing predecessor history commitment"
            )

        expected_digest = row[0]

    if predecessor[2] != expected_digest:
        raise ValueError(
            "Predecessor anchor digest mismatch"
        )

    disk_predecessor = read_history_anchor(
        anchor_path, key
    )

    if disk_predecessor != predecessor:
        raise ValueError(
            "On-disk anchor does not match predecessor"
        )

    return {
        "state": "ELIGIBLE_FOR_PUBLICATION",
        "stream_id": stream_id,
        "previous_sequence": predecessor[1],
        "previous_digest": predecessor[2],
        "sequence": sequence,
        "digest": intent["history_digest"],
        "intent": intent,
    }
