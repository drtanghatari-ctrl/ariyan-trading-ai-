"""A006-WB02-P3C10 — Owned SQLite read-snapshot boundary.

Opens an existing ledger read-only, establishes a SQLite snapshot,
and delegates enrollment verification to P3C9.

No writes, enrollment, independent trust authentication,
rollback protection, or trading authorization.
"""

import sqlite3
from pathlib import Path

from ariyan_trading.verified_enrollment_assessment import (
    assess_verified_enrollment,
)


def assess_enrollment_snapshot(
    database_path,
    opening_cash,
    anchor_path,
    checkpoint_key,
    policy_record,
    policy_key,
    lookup,
    *,
    publication_uncertain=False,
):
    """Assess enrollment within an owned read-only SQLite transaction."""

    path = Path(database_path)

    if not path.is_file():
        raise ValueError("Existing ledger database required")

    uri = path.resolve().as_uri() + "?mode=ro"

    db = sqlite3.connect(
        uri,
        uri=True,
        isolation_level=None,
        timeout=10,
    )

    try:
        db.execute("BEGIN")

        # Acquire the read snapshot before external checkpoint I/O.
        db.execute(
            "SELECT name FROM sqlite_master LIMIT 1"
        ).fetchall()

        return assess_verified_enrollment(
            db,
            opening_cash,
            anchor_path,
            checkpoint_key,
            policy_record,
            policy_key,
            lookup,
            publication_uncertain=publication_uncertain,
        )

    finally:
        try:
            if db.in_transaction:
                db.rollback()
        finally:
            db.close()
