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
