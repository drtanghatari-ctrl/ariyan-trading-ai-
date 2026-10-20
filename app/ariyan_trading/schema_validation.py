"""Fail-closed validation of durable ledger SQLite schema."""


def _columns(db, table):
    rows = db.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    if not rows:
        raise ValueError(f"Missing or empty schema: {table}")

    return {
        row[1]: {
            "type": row[2].upper(),
            "notnull": bool(row[3]),
            "pk": row[5],
        }
        for row in rows
    }


def _require_column(
    columns, name, expected_type,
    *, notnull=False, primary_key=False
):
    col = columns.get(name)

    if col is None:
        raise ValueError(f"Missing column: {name}")

    if col["type"] != expected_type:
        raise ValueError(f"Invalid column type: {name}")

    if primary_key and col["pk"] != 1:
        raise ValueError(f"Missing primary key: {name}")

    if notnull and not col["notnull"]:
        raise ValueError(f"Missing NOT NULL: {name}")


def _has_unique_index(db, table, column):
    for row in db.execute(
        f"PRAGMA index_list({table})"
    ):
        index_name = row[1]
        is_unique = bool(row[2])

        if not is_unique:
            continue

        escaped = index_name.replace('"', '""')
        indexed = db.execute(
            f'PRAGMA index_info("{escaped}")'
        ).fetchall()

        if len(indexed) == 1 and indexed[0][2] == column:
            return True

    return False


def validate_ledger_schema(db):
    """Reject missing or structurally invalid ledger tables."""

    meta = _columns(db, "ledger_meta")

    _require_column(
        meta, "key", "TEXT", primary_key=True
    )
    _require_column(
        meta, "value", "TEXT", notnull=True
    )

    journal = _columns(db, "ledger_entries")

    _require_column(
        journal, "sequence", "INTEGER",
        primary_key=True
    )

    for name in (
        "request_id",
        "action",
        "quantity",
        "price",
        "cash_delta",
        "units_delta",
    ):
        _require_column(
            journal, name, "TEXT", notnull=True
        )

    if not _has_unique_index(
        db, "ledger_entries", "request_id"
    ):
        raise ValueError(
            "Journal request_id lacks UNIQUE constraint"
        )
