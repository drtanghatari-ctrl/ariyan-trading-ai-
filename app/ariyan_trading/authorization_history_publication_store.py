"""A006 C2D-04B2B transactional publication-intent primitive.

No history append, anchor publication, recovery, freshness guarantee,
financial mutation, or trading authorization.
"""

import json

from .authorization_history_publication_control import (
    verify_publication_control,
)
from .authorization_history_publication_intent import (
    canonical_publication_intent,
    validate_publication_intent,
)
from .authorization_status_history_store import verify_history_store


def record_publication_intent(db, intent):
    """Record one pending intent in a caller-owned SQLite transaction.

    The caller must commit the corresponding history append and this
    intent together. This function does not authenticate the previous
    checkpoint or enforce that an append occurred in this transaction.
    """

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    validate_publication_intent(intent)

    # Acquire SQLite's writer reservation before reading publication
    # control or the history tip. A deferred transaction must upgrade
    # successfully or fail without recording an intent.
    db.execute(
        "UPDATE auth_pubctl_state SET value=value "
        "WHERE key='version'"
    )

    # Strict READY verification rejects an existing pending intent,
    # unexpected metadata, or unexpected publication-control schema.
    if verify_publication_control(db) != "READY":
        raise ValueError("Publication control is not ready")

    sequence, digest = verify_history_store(
        db, intent["stream_id"]
    )

    if (
        sequence != intent["history_sequence"]
        or digest != intent["history_digest"]
    ):
        raise ValueError("Publication intent does not match history tip")

    payload = canonical_publication_intent(intent).decode("ascii")

    db.execute("SAVEPOINT auth_pubctl_record")

    try:
        cursor = db.execute(
            "UPDATE auth_pubctl_state SET value='PENDING' "
            "WHERE key='publication_state' AND value='READY'"
        )

        if cursor.rowcount != 1:
            raise ValueError("Publication state changed")

        db.execute(
            "INSERT INTO auth_pubctl_state(key,value) VALUES (?,?)",
            ("publication_intent", payload),
        )

    except BaseException:
        try:
            db.execute("ROLLBACK TO SAVEPOINT auth_pubctl_record")
        finally:
            db.execute("RELEASE SAVEPOINT auth_pubctl_record")
        raise

    db.execute("RELEASE SAVEPOINT auth_pubctl_record")

    return sequence, digest


def verify_pending_publication_intent(db, stream_id):
    """Validate stored PENDING metadata and its current history tip.

    This is structural verification, not authentication or freshness
    verification. It does not authorize anchor publication.
    """

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    # Check the protected schema without treating PENDING as READY.
    from .authorization_history_publication_control import _verify_schema

    _verify_schema(db)

    rows = db.execute(
        "SELECT key,value FROM auth_pubctl_state"
    ).fetchall()

    metadata = dict(rows)

    if (
        len(rows) != 3
        or set(metadata) != {
            "version",
            "publication_state",
            "publication_intent",
        }
    ):
        raise ValueError("Invalid pending publication metadata")

    from .authorization_history_publication_control import VERSION

    if (
        metadata["version"] != VERSION
        or metadata["publication_state"] != "PENDING"
    ):
        raise ValueError("Invalid pending publication state")

    raw = metadata["publication_intent"]

    try:
        intent = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid stored publication intent") from exc

    validate_publication_intent(intent)

    if canonical_publication_intent(intent).decode("ascii") != raw:
        raise ValueError("Noncanonical stored publication intent")

    if intent["stream_id"] != stream_id:
        raise ValueError("Publication stream mismatch")

    sequence, digest = verify_history_store(db, stream_id)

    if (
        sequence != intent["history_sequence"]
        or digest != intent["history_digest"]
    ):
        raise ValueError("Pending intent does not match history tip")

    return intent
