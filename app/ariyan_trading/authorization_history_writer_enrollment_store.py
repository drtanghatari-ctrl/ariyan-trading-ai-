"""A006 C2D-04B2C4B1 authorization-history enrollment storage.

Transactional SQLite storage with strict schema validation.

Does not authenticate stored policy, enroll an active writer,
enforce append restrictions, prevent rollback or downgrade,
or authorize financial operations.
"""

import json

from .authorization_history_writer_policy import (
    VERSION,
    WRITER_MODE,
)
from .authorization_validation import valid_uuid


TABLE = "auth_writer_enrollment_state"

EXPECTED_SQL = (
    "CREATE TABLE auth_writer_enrollment_state ("
    "key TEXT PRIMARY KEY, "
    "value TEXT NOT NULL)"
)

NAMESPACE = "auth_writer_enrollment_"


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
            name.startswith(NAMESPACE)
            or table_name.startswith(NAMESPACE)
        ):
            raise ValueError(
                "Unexpected temporary enrollment object"
            )

    protected = [
        (kind, name, table_name, sql)
        for kind, name, table_name, sql in objects
        if (
            name.startswith(NAMESPACE)
            or table_name.startswith(NAMESPACE)
        )
        and not (
            kind == "index"
            and name
            == "sqlite_autoindex_auth_writer_enrollment_state_1"
            and sql is None
        )
    ]

    if protected != [
        ("table", TABLE, TABLE, EXPECTED_SQL)
    ]:
        raise ValueError("Enrollment schema mismatch")

    indexes = db.execute(
        "PRAGMA index_list('auth_writer_enrollment_state')"
    ).fetchall()

    if (
        len(indexes) != 1
        or indexes[0][1]
        != "sqlite_autoindex_auth_writer_enrollment_state_1"
        or indexes[0][2] != 1
        or indexes[0][3] != "pk"
        or indexes[0][4] != 0
    ):
        raise ValueError(
            "Enrollment primary-key index mismatch"
        )


def initialize_enrollment_store(db, policy):
    """Store one policy inside a caller-owned transaction.

    Structural storage only. The supplied policy must already have
    been authenticated by a trusted caller.
    """

    _require_transaction(db)

    existing = db.execute(
        "SELECT name,tbl_name FROM sqlite_master"
    ).fetchall()

    if any(
        name.startswith(NAMESPACE)
        or table_name.startswith(NAMESPACE)
        for name, table_name in existing
    ):
        raise ValueError(
            "Enrollment namespace already exists"
        )

    temporary = db.execute(
        "SELECT name,tbl_name FROM sqlite_temp_master"
    ).fetchall()

    if any(
        name.startswith(NAMESPACE)
        or table_name.startswith(NAMESPACE)
        for name, table_name in temporary
    ):
        raise ValueError(
            "Temporary enrollment namespace collision"
        )

    if type(policy) is not dict:
        raise ValueError("Invalid enrollment policy")

    # Canonical serialization, without authentication.
    payload = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    db.execute(EXPECTED_SQL)

    db.execute(
        "INSERT INTO auth_writer_enrollment_state "
        "(key,value) VALUES (?,?)",
        ("policy", payload),
    )


def read_enrollment_policy(db):
    """Read a structurally valid stored policy, without MAC verification."""

    _require_transaction(db)
    _verify_schema(db)

    rows = db.execute(
        "SELECT key,value FROM auth_writer_enrollment_state"
    ).fetchall()

    if len(rows) != 1 or rows[0][0] != "policy":
        raise ValueError(
            "Invalid enrollment metadata"
        )

    raw = rows[0][1]

    try:
        policy = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Invalid stored enrollment JSON"
        ) from exc

    if type(policy) is not dict:
        raise ValueError(
            "Invalid stored enrollment policy"
        )

    expected_fields = {
        "version",
        "stream_id",
        "writer_mode",
        "enrollment_sequence",
        "enrollment_digest",
        "mac",
    }

    if set(policy) != expected_fields:
        raise ValueError("Invalid enrollment policy fields")

    if (
        policy["version"] != VERSION
        or policy["writer_mode"] != WRITER_MODE
        or not valid_uuid(policy["stream_id"])
    ):
        raise ValueError("Invalid enrollment policy identity")

    sequence = policy["enrollment_sequence"]

    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid enrollment sequence")

    for field in ("enrollment_digest", "mac"):
        value = policy[field]

        if type(value) is not str or len(value) != 64:
            raise ValueError("Invalid enrollment hexadecimal field")

        try:
            decoded_hex = bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError(
                "Invalid enrollment hexadecimal field"
            ) from exc

        if (
            len(decoded_hex) != 32
            or decoded_hex.hex() != value
        ):
            raise ValueError(
                "Noncanonical enrollment hexadecimal field"
            )

    canonical = json.dumps(
        policy,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )

    if canonical != raw:
        raise ValueError(
            "Noncanonical enrollment policy"
        )

    return policy
