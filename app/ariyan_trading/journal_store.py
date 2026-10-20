"""Versioned SQLite journal commitment storage.

This module does not authenticate database history against an
attacker who can rewrite both transactions and commitments.
"""

from .journal_commitment import opening_commitment


VERSION = "sha256-chain-v1"


def create_protected_journal(db, opening_cash):
    """Initialize protection for a newly created ledger.

    Must be called inside the ledger initialization transaction.
    """
    db.execute(
        "CREATE TABLE journal_commitments ("
        "sequence INTEGER PRIMARY KEY, "
        "digest TEXT NOT NULL)"
    )

    db.execute(
        "INSERT INTO ledger_meta(key,value) "
        "VALUES ('journal_protection',?)",
        (VERSION,),
    )

    db.execute(
        "INSERT INTO ledger_meta(key,value) "
        "VALUES ('journal_genesis',?)",
        (opening_commitment(str(opening_cash)),),
    )


def protection_status(db):
    """Classify a database without silently enrolling legacy data."""
    rows = dict(
        db.execute(
            "SELECT key,value FROM ledger_meta "
            "WHERE key IN ('journal_protection','journal_genesis')"
        ).fetchall()
    )

    table_exists = db.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='journal_commitments'"
    ).fetchone() is not None

    if not rows and not table_exists:
        return "legacy-unsealed"

    if (
        rows.get("journal_protection") != VERSION
        or "journal_genesis" not in rows
        or not table_exists
    ):
        raise ValueError("Incomplete journal protection metadata")

    return "protected"


def verify_protected_journal(db, opening_cash):
    """Verify every protected journal row against its stored digest.

    Caller must provide a consistent SQLite transaction snapshot.
    """
    from .journal_commitment import entry_commitment

    if protection_status(db) != "protected":
        raise ValueError("Journal is not protected")

    genesis = opening_commitment(str(opening_cash))

    stored_genesis = db.execute(
        "SELECT value FROM ledger_meta "
        "WHERE key='journal_genesis'"
    ).fetchone()[0]

    if stored_genesis != genesis:
        raise ValueError("Journal genesis mismatch")

    rows = db.execute(
        "SELECT sequence,request_id,action,quantity,price,"
        "cash_delta,units_delta "
        "FROM ledger_entries ORDER BY sequence"
    ).fetchall()

    commitments = db.execute(
        "SELECT sequence,digest "
        "FROM journal_commitments ORDER BY sequence"
    ).fetchall()

    if len(rows) != len(commitments):
        raise ValueError("Journal commitment count mismatch")

    previous = genesis

    for expected_sequence, (row, commitment) in enumerate(
        zip(rows, commitments), start=1
    ):
        sequence = row[0]
        committed_sequence, stored_digest = commitment

        if (
            sequence != expected_sequence
            or committed_sequence != expected_sequence
        ):
            raise ValueError("Journal commitment sequence mismatch")

        expected_digest = entry_commitment(previous, *row)

        if stored_digest != expected_digest:
            raise ValueError("Journal commitment mismatch")

        previous = expected_digest

    return previous



def append_journal_commitment(db, opening_cash):
    """Commit exactly one new entry inside an active transaction.

    The caller owns COMMIT and ROLLBACK.
    """
    from .journal_commitment import entry_commitment

    if not db.in_transaction:
        raise ValueError(
            "An active SQLite transaction is required"
        )

    if protection_status(db) != "protected":
        raise ValueError("Journal is not protected")

    rows = db.execute(
        "SELECT sequence,request_id,action,quantity,price,"
        "cash_delta,units_delta "
        "FROM ledger_entries ORDER BY sequence"
    ).fetchall()

    if not rows:
        raise ValueError("No journal entry to commit")

    commitments = db.execute(
        "SELECT sequence,digest "
        "FROM journal_commitments ORDER BY sequence"
    ).fetchall()

    if len(rows) != len(commitments) + 1:
        raise ValueError(
            "Expected exactly one uncommitted journal entry"
        )

    genesis = opening_commitment(str(opening_cash))

    stored_genesis = db.execute(
        "SELECT value FROM ledger_meta "
        "WHERE key='journal_genesis'"
    ).fetchone()[0]

    if stored_genesis != genesis:
        raise ValueError("Journal genesis mismatch")

    previous = genesis

    for index, (sequence, digest) in enumerate(
        commitments, start=1
    ):
        row = rows[index - 1]

        if sequence != index or row[0] != index:
            raise ValueError(
                "Previously committed sequence mismatch"
            )

        expected = entry_commitment(previous, *row)

        if digest != expected:
            raise ValueError(
                "Previously committed journal was modified"
            )

        previous = expected

    new_row = rows[-1]
    new_sequence = len(commitments) + 1

    if new_row[0] != new_sequence:
        raise ValueError("New journal sequence mismatch")

    digest = entry_commitment(previous, *new_row)

    db.execute(
        "INSERT INTO journal_commitments(sequence,digest) "
        "VALUES (?,?)",
        (new_sequence, digest),
    )

    return digest
