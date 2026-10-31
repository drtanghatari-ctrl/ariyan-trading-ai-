"""A006 C2D-04B2C3B durable authorization-history publication.

Publishes one already committed pending authorization-history checkpoint.

No history append, automatic recovery, independent freshness,
rollback resistance, financial mutation, or trading authorization.
"""

from .authorization_history_anchor import (
    create_history_anchor,
)
from .authorization_history_anchor_io import (
    read_history_anchor,
    write_history_anchor,
)
from .authorization_history_publication_eligibility import (
    verify_history_publication_eligibility,
)
from .authorization_history_publication_control import (
    verify_publication_control,
)
from .authorization_history_publication_path_guard import (
    verify_history_anchor_path,
)


class HistoryPublicationUncertain(RuntimeError):
    """Publication outcome requires inspection; do not retry."""


def publish_prepared_history(
    db, stream_id, predecessor_anchor, anchor_path, key
):
    """Publish one pending history checkpoint under SQLite writer lock.

    The caller must not share the SQLite connection concurrently.
    The supplied predecessor anchor must originate from an independently
    selected trusted checkpoint source.

    Any failure after publication starts is uncertain and cannot
    authorize an automatic retry.
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

    anchor_path = verify_history_anchor_path(db, anchor_path)

    publication_started = False

    try:
        db.execute("BEGIN IMMEDIATE")

        eligible = verify_history_publication_eligibility(
            db,
            stream_id,
            predecessor_anchor,
            anchor_path,
            key,
        )

        sequence = eligible["sequence"]
        digest = eligible["digest"]

        next_anchor = create_history_anchor(
            stream_id, sequence, digest, key
        )

        publication_started = True

        write_history_anchor(
            anchor_path, next_anchor, key
        )

        if read_history_anchor(anchor_path, key) != (
            stream_id, sequence, digest
        ):
            raise ValueError(
                "Published history anchor readback mismatch"
            )

        intent_payload = db.execute(
            "SELECT value FROM auth_pubctl_state "
            "WHERE key='publication_intent'"
        ).fetchone()

        if intent_payload is None:
            raise ValueError(
                "Publication intent disappeared"
            )

        cursor = db.execute(
            "DELETE FROM auth_pubctl_state "
            "WHERE key='publication_intent' AND value=?",
            (intent_payload[0],),
        )

        if cursor.rowcount != 1:
            raise ValueError(
                "Publication intent changed"
            )

        cursor = db.execute(
            "UPDATE auth_pubctl_state SET value='READY' "
            "WHERE key='publication_state' AND value='PENDING'"
        )

        if cursor.rowcount != 1:
            raise ValueError(
                "Publication state changed"
            )

        if verify_publication_control(db) != "READY":
            raise ValueError(
                "Publication control not restored"
            )

        db.execute("COMMIT")

    except BaseException as exc:
        rollback_error = None

        try:
            if db.in_transaction:
                db.rollback()
        except BaseException as rollback_exc:
            rollback_error = rollback_exc

        if publication_started or rollback_error is not None:
            error = HistoryPublicationUncertain(
                "Authorization-history publication outcome "
                "requires inspection; do not retry automatically"
            )

            if rollback_error is not None:
                error.add_note(
                    "Rollback also failed: "
                    + repr(rollback_error)
                )

            raise error from exc

        raise

    return {
        "state": "DURABLE",
        "stream_id": stream_id,
        "sequence": sequence,
        "digest": digest,
    }
