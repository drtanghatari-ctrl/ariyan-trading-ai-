"""A006 C2D-04B2C3B authorization-history anchor path guard.

Rejects database-file collisions and aliases before publication.
This is not a defense against concurrent filesystem path replacement.
"""

from pathlib import Path


def verify_history_anchor_path(db, anchor_path):
    """Reject anchor paths overlapping the main SQLite database."""

    rows = db.execute("PRAGMA database_list").fetchall()

    main = [
        row[2]
        for row in rows
        if row[1] == "main"
    ]

    if len(main) != 1 or not main[0]:
        raise ValueError(
            "Persistent main SQLite database required"
        )

    database = Path(main[0]).resolve(strict=True)
    anchor = Path(anchor_path).resolve(strict=False)

    reserved = {
        database,
        Path(str(database) + "-wal"),
        Path(str(database) + "-shm"),
        Path(str(database) + "-journal"),
    }

    if anchor in reserved:
        raise ValueError(
            "Anchor path overlaps SQLite database files"
        )

    if anchor.exists():
        for candidate in reserved:
            if candidate.exists() and anchor.samefile(candidate):
                raise ValueError(
                    "Anchor aliases a SQLite database file"
                )

    return anchor
