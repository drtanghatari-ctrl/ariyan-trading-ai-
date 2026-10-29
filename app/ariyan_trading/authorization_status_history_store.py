"""A006 P3C12-B6C3C2C2: authorization-history SQLite storage.

Transactional storage primitives and internal chain verification.

No independent authentication, trusted freshness, rollback resistance,
automatic repair, financial ledger mutation, or trading authorization.
"""

import sqlite3

from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
    entry_history_commitment,
)
from ariyan_trading.authorization_status_history_decoder import (
    decode_status_history_entry,
)


STORE_VERSION = "ARIYAN-A006-AUTH-HISTORY-STORE-V1"


def _table_names(db):
    return {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'authorization_history_%'"
        )
    }


def initialize_history_store(db, stream_id):
    """Initialize a new history store inside a caller-owned transaction."""

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    genesis = opening_history_commitment(stream_id)

    if _table_names(db):
        raise ValueError("Authorization-history tables already exist")

    db.execute(
        "CREATE TABLE authorization_history_meta ("
        "key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL)"
    )

    db.execute(
        "CREATE TABLE authorization_history_entries ("
        "history_sequence INTEGER PRIMARY KEY, "
        "payload BLOB NOT NULL)"
    )

    db.execute(
        "CREATE TABLE authorization_history_commitments ("
        "history_sequence INTEGER PRIMARY KEY, "
        "digest TEXT NOT NULL)"
    )

    db.executemany(
        "INSERT INTO authorization_history_meta(key,value) VALUES (?,?)",
        [
            ("version", STORE_VERSION),
            ("stream_id", stream_id),
            ("genesis_digest", genesis),
        ],
    )

    return genesis


def verify_history_store(db, stream_id):
    """Verify a complete stored history in a consistent transaction."""

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    expected_tables = {
        "authorization_history_meta",
        "authorization_history_entries",
        "authorization_history_commitments",
    }

    if _table_names(db) != expected_tables:
        raise ValueError("Incomplete authorization-history schema")

    metadata = db.execute(
        "SELECT key,value FROM authorization_history_meta"
    ).fetchall()

    if len(metadata) != 3:
        raise ValueError("Invalid authorization-history metadata count")

    metadata = dict(metadata)

    genesis = opening_history_commitment(stream_id)

    if metadata != {
        "version": STORE_VERSION,
        "stream_id": stream_id,
        "genesis_digest": genesis,
    }:
        raise ValueError("Authorization-history metadata mismatch")

    entries = db.execute(
        "SELECT history_sequence,payload "
        "FROM authorization_history_entries "
        "ORDER BY history_sequence"
    ).fetchall()

    commitments = db.execute(
        "SELECT history_sequence,digest "
        "FROM authorization_history_commitments "
        "ORDER BY history_sequence"
    ).fetchall()

    if len(entries) != len(commitments):
        raise ValueError("Authorization-history commitment count mismatch")

    previous = genesis

    for expected_sequence, (entry_row, commitment_row) in enumerate(
        zip(entries, commitments),
        start=1,
    ):
        sequence, payload = entry_row
        commitment_sequence, stored_digest = commitment_row

        if (
            type(sequence) is not int
            or sequence != expected_sequence
            or type(commitment_sequence) is not int
            or commitment_sequence != expected_sequence
        ):
            raise ValueError("Authorization-history sequence discontinuity")

        entry = decode_status_history_entry(payload)

        if entry.stream_id != stream_id:
            raise ValueError("Authorization-history stream mismatch")

        if entry.history_sequence != expected_sequence:
            raise ValueError("Authorization-history entry sequence mismatch")

        expected_digest = entry_history_commitment(previous, entry)

        if stored_digest != expected_digest:
            raise ValueError("Authorization-history commitment mismatch")

        previous = expected_digest

    return len(entries), previous


def append_history_entry(db, stream_id, entry):
    """Append one entry and commitment in a caller-owned transaction.

    Caller must acquire a SQLite write transaction using BEGIN IMMEDIATE
    before invoking this function, and must COMMIT or ROLLBACK afterward.

    This function does not authenticate authorization evidence or
    independently prevent history rollback.
    """

    from ariyan_trading.authorization_status_history import (
        canonical_status_history_entry,
        validate_status_history_entry,
    )

    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")

    if not validate_status_history_entry(entry):
        raise ValueError("Invalid authorization-history entry")

    if entry.stream_id != stream_id:
        raise ValueError("Authorization-history stream mismatch")

    # Acquire SQLite's writer reservation before verifying history.
    # This also works when the caller began a deferred transaction,
    # provided it can be upgraded to a writer.
    db.execute(
        "UPDATE authorization_history_meta "
        "SET value=value WHERE key='version'"
    )

    sequence, previous_digest = verify_history_store(db, stream_id)

    expected_sequence = sequence + 1

    if entry.history_sequence != expected_sequence:
        raise ValueError("Authorization-history sequence mismatch")

    payload = canonical_status_history_entry(entry)

    next_digest = entry_history_commitment(previous_digest, entry)

    db.execute("SAVEPOINT authorization_history_append")

    try:
        db.execute(
            "INSERT INTO authorization_history_entries "
            "(history_sequence,payload) VALUES (?,?)",
            (expected_sequence, payload),
        )

        db.execute(
            "INSERT INTO authorization_history_commitments "
            "(history_sequence,digest) VALUES (?,?)",
            (expected_sequence, next_digest),
        )

    except BaseException:
        try:
            db.execute(
                "ROLLBACK TO SAVEPOINT authorization_history_append"
            )
        finally:
            db.execute(
                "RELEASE SAVEPOINT authorization_history_append"
            )
        raise

    db.execute("RELEASE SAVEPOINT authorization_history_append")

    return expected_sequence, next_digest
