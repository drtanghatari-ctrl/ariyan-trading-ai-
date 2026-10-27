"""A006-WB02-P3B authenticated enrollment evidence verification.

Read-only verification only. Does not enroll ledgers, authorize
trades, publish policies, or provide independent rollback resistance.
"""

from .checkpoint_verifier import verify_checkpoint
from .ledger_identity import read_ledger_identity
from .writer_policy import verify_writer_policy


def verify_enrollment(
    db,
    opening_cash,
    anchor_path,
    checkpoint_key,
    policy_record,
    policy_key,
):
    """Verify authenticated policy against checkpointed journal history.

    Caller must supply a stable SQLite transaction snapshot.
    No database or filesystem changes are performed.
    """
    if not db.in_transaction:
        raise ValueError("Active transaction required")

    sequence, _ = verify_checkpoint(
        db, opening_cash, anchor_path, checkpoint_key
    )

    policy = verify_writer_policy(policy_record, policy_key)

    identity = read_ledger_identity(db)
    if identity is None:
        raise ValueError("Ledger identity missing")

    if policy["ledger_id"] != identity:
        raise ValueError("Enrollment ledger identity mismatch")

    enrolled_sequence = policy["enrollment_sequence"]

    if enrolled_sequence > sequence:
        raise ValueError("Enrollment sequence exceeds journal tip")

    if enrolled_sequence == 0:
        row = db.execute(
            "SELECT value FROM ledger_meta "
            "WHERE key='journal_genesis'"
        ).fetchone()
    else:
        row = db.execute(
            "SELECT digest FROM journal_commitments "
            "WHERE sequence=?",
            (enrolled_sequence,),
        ).fetchone()

    if row is None:
        raise ValueError("Enrollment historical commitment missing")

    if row[0] != policy["enrollment_digest"]:
        raise ValueError("Enrollment historical digest mismatch")

    return policy
