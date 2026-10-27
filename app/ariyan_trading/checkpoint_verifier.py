"""A006 read-only journal checkpoint verification.

This module does not create anchors, coordinate commits,
or establish independent rollback resistance.
"""

from .journal_store import (
    protection_status,
    verify_protected_journal,
)
from .trust_anchor import read_anchor


def verify_checkpoint(db, opening_cash, anchor_path, key):
    """Compare an authenticated checkpoint with a verified journal tip.

    Requires a stable SQLite snapshot supplied by the caller.
    Rejects missing, stale, or divergent checkpoints.
    """
    if not db.in_transaction:
        raise ValueError(
            "An active SQLite transaction is required"
        )

    pending = db.execute(
        "SELECT value FROM ledger_meta "
        "WHERE key='checkpoint_publication_pending'"
    ).fetchone()
    if pending is not None:
        raise ValueError("Checkpoint publication outcome is pending or uncertain")

    if protection_status(db) != "protected":
        raise ValueError("Unprotected journal cannot be anchored")

    journal_digest = verify_protected_journal(
        db, opening_cash
    )

    row = db.execute(
        "SELECT COUNT(*) FROM ledger_entries"
    ).fetchone()
    sequence = row[0]

    anchored_sequence, anchored_digest = read_anchor(
        anchor_path, key
    )

    if anchored_sequence != sequence:
        raise ValueError("Checkpoint sequence mismatch")

    if anchored_digest != journal_digest:
        raise ValueError("Checkpoint digest mismatch")

    return sequence, journal_digest
