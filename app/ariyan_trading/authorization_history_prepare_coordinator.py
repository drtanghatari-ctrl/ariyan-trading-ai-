"""A006 C2D-04B2C2 atomic authorization-history preparation.

Coordinates one authenticated history append and matching publication
intent in one SQLite transaction.

Does not publish external anchors, recover uncertain outcomes,
establish independent freshness, enforce all writer boundaries,
mutate financial state, or authorize trading.
"""

from .authorization_history_publication_preflight import (
    verify_history_publication_preflight,
)
from .authorization_history_publication_intent import (
    create_publication_intent,
)
from .authorization_history_publication_store import (
    record_publication_intent,
)
from .authorization_status_history_store import (
    append_history_entry,
)


class HistoryPreparationUncertain(RuntimeError):
    """Database commit was attempted; outcome requires inspection."""


def prepare_history_publication(
    db, stream_id, entry, anchor, key
):
    """Commit one history append and matching pending intent.

    The caller owns the SQLite connection and must not share it
    concurrently.

    The anchor must originate from an independently selected trusted
    checkpoint source. This function does not verify its freshness.

    Successful return means PENDING_PUBLICATION, not publication.
    """

    if db.in_transaction:
        raise ValueError(
            "Coordinator requires an idle SQLite connection"
        )

    synchronous = db.execute(
        "PRAGMA synchronous"
    ).fetchone()[0]

    if synchronous not in (2, 3):
        raise ValueError(
            "SQLite FULL or EXTRA synchronous mode required"
        )

    commit_attempted = False

    try:
        db.execute("BEGIN IMMEDIATE")

        previous_sequence, previous_digest = (
            verify_history_publication_preflight(
                db, stream_id, anchor, key
            )
        )

        sequence, digest = append_history_entry(
            db, stream_id, entry
        )

        if sequence != previous_sequence + 1:
            raise ValueError(
                "Unexpected authorization-history sequence"
            )

        intent = create_publication_intent(
            stream_id, sequence, digest
        )

        recorded = record_publication_intent(
            db, intent
        )

        if recorded != (sequence, digest):
            raise ValueError(
                "Publication intent does not match appended history"
            )

        commit_attempted = True
        db.execute("COMMIT")

    except BaseException as exc:
        rollback_error = None

        try:
            if db.in_transaction:
                db.rollback()
        except BaseException as rollback_exc:
            rollback_error = rollback_exc

        if commit_attempted or rollback_error is not None:
            error = HistoryPreparationUncertain(
                "History transaction outcome requires inspection; "
                "do not retry or publish automatically"
            )

            if rollback_error is not None:
                error.add_note(
                    "Rollback also failed: "
                    + repr(rollback_error)
                )

            raise error from exc

        raise

    return {
        "state": "PENDING_PUBLICATION",
        "stream_id": stream_id,
        "previous_sequence": previous_sequence,
        "previous_digest": previous_digest,
        "sequence": sequence,
        "digest": digest,
        "intent": intent,
    }
