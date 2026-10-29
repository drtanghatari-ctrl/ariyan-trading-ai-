"""A006 C2D-04B1 publication-control schema foundation.

Separate namespace from protected authorization-history evidence.

No history mutation, anchor publication, recovery, freshness guarantee,
or trading authorization.
"""

VERSION = "ARIYAN-A006-AUTH-PUBCTL-V1"

TABLE = "auth_pubctl_state"

EXPECTED_SQL = (
    "CREATE TABLE auth_pubctl_state ("
    "key TEXT PRIMARY KEY, "
    "value TEXT NOT NULL)"
)

EXPECTED_METADATA = {
    "version": VERSION,
    "publication_state": "READY",
}


def _require_transaction(db):
    if not db.in_transaction:
        raise ValueError("Active SQLite transaction required")


def _verify_schema(db):
    objects = db.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master"
    ).fetchall()

    temporary = db.execute(
        "SELECT type,name,tbl_name FROM sqlite_temp_master"
    ).fetchall()

    for kind, name, table_name in temporary:
        if (
            name.startswith("auth_pubctl_")
            or table_name.startswith("auth_pubctl_")
        ):
            raise ValueError("Unexpected temporary publication-control object")

    protected = [
        (kind, name, table_name, sql)
        for kind, name, table_name, sql in objects
        if (
            name.startswith("auth_pubctl_")
            or table_name.startswith("auth_pubctl_")
        )
        and not (
            kind == "index"
            and name == "sqlite_autoindex_auth_pubctl_state_1"
            and sql is None
        )
    ]

    if protected != [("table", TABLE, TABLE, EXPECTED_SQL)]:
        raise ValueError("Publication-control schema mismatch")

    indexes = db.execute(
        "PRAGMA index_list('auth_pubctl_state')"
    ).fetchall()

    if (
        len(indexes) != 1
        or indexes[0][1] != "sqlite_autoindex_auth_pubctl_state_1"
        or indexes[0][2] != 1
        or indexes[0][3] != "pk"
        or indexes[0][4] != 0
    ):
        raise ValueError("Publication-control primary-key index mismatch")


def initialize_publication_control(db):
    """Initialize publication-control metadata in caller transaction."""
    _require_transaction(db)

    existing = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE name LIKE 'auth_pubctl_%'"
    ).fetchall()

    if existing:
        raise ValueError("Publication-control namespace already exists")

    _verify_no_temporary_objects(db)

    db.execute(EXPECTED_SQL)

    db.executemany(
        "INSERT INTO auth_pubctl_state(key,value) VALUES (?,?)",
        sorted(EXPECTED_METADATA.items()),
    )


def _verify_no_temporary_objects(db):
    objects = db.execute(
        "SELECT name,tbl_name FROM sqlite_temp_master"
    ).fetchall()

    for name, table_name in objects:
        if (
            name.startswith("auth_pubctl_")
            or table_name.startswith("auth_pubctl_")
        ):
            raise ValueError("Unexpected temporary publication-control object")


def verify_publication_control(db):
    """Verify strict schema and initial READY metadata."""
    _require_transaction(db)
    _verify_schema(db)

    rows = db.execute(
        "SELECT key,value FROM auth_pubctl_state"
    ).fetchall()

    if len(rows) != len(EXPECTED_METADATA):
        raise ValueError("Invalid publication-control metadata count")

    metadata = dict(rows)

    if metadata != EXPECTED_METADATA:
        raise ValueError("Publication-control metadata mismatch")

    return metadata["publication_state"]
