"""A006 C2D-04B2C4B2 authenticated enrollment verification.

Read-only verification of an enrolled history writer policy
against a caller-supplied authenticated enrollment checkpoint.

No independent freshness, rollback resistance, writer-boundary
enforcement, financial mutation, or trading authorization.
"""

from .authorization_history_anchor import verify_history_anchor
from .authorization_history_writer_enrollment_store import (
    read_enrollment_policy,
)
from .authorization_history_writer_policy import (
    verify_history_writer_policy,
)
from .authorization_status_history_commitment import (
    opening_history_commitment,
)
from .authorization_status_history_store import (
    verify_history_store,
)


def verify_authenticated_writer_enrollment(
    db, stream_id, enrollment_anchor, key
):
    """Verify policy, checkpoint, and locally committed history.

    The caller must supply the enrollment anchor from an
    independently selected trusted source.

    The key must be protected outside the database.

    Successful verification does not establish freshness.
    """

    if not db.in_transaction:
        raise ValueError(
            "Active SQLite transaction required"
        )

    stored_policy = read_enrollment_policy(db)

    policy = verify_history_writer_policy(
        stored_policy, key
    )

    if policy["stream_id"] != stream_id:
        raise ValueError(
            "Enrollment policy stream mismatch"
        )

    anchor_stream, anchor_sequence, anchor_digest = (
        verify_history_anchor(enrollment_anchor, key)
    )

    if anchor_stream != stream_id:
        raise ValueError(
            "Enrollment anchor stream mismatch"
        )

    enrollment_sequence = policy["enrollment_sequence"]
    enrollment_digest = policy["enrollment_digest"]

    if (
        anchor_sequence != enrollment_sequence
        or anchor_digest != enrollment_digest
    ):
        raise ValueError(
            "Enrollment policy and anchor mismatch"
        )

    current_sequence, current_digest = verify_history_store(
        db, stream_id
    )

    if enrollment_sequence > current_sequence:
        raise ValueError(
            "Enrollment checkpoint exceeds history tip"
        )

    if enrollment_sequence == 0:
        expected_digest = opening_history_commitment(
            stream_id
        )
    else:
        row = db.execute(
            "SELECT digest "
            "FROM authorization_history_commitments "
            "WHERE history_sequence=?",
            (enrollment_sequence,),
        ).fetchone()

        if row is None:
            raise ValueError(
                "Missing enrollment history commitment"
            )

        expected_digest = row[0]

    if expected_digest != enrollment_digest:
        raise ValueError(
            "Enrollment history commitment mismatch"
        )

    return {
        "state": "AUTHENTICATED_ENROLLMENT",
        "stream_id": stream_id,
        "writer_mode": policy["writer_mode"],
        "enrollment_sequence": enrollment_sequence,
        "enrollment_digest": enrollment_digest,
        "current_sequence": current_sequence,
        "current_digest": current_digest,
    }
