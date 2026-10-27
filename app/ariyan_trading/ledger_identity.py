"""A006-WB02 persistent ledger identity primitives.

A UUID identifies a ledger but does not authenticate it.
"""

import uuid


IDENTITY_KEY = "ledger_identity"


def new_ledger_identity():
    return str(uuid.uuid4())


def validate_ledger_identity(value):
    if not isinstance(value, str):
        raise ValueError("Invalid ledger identity")

    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise ValueError("Invalid ledger identity") from exc

    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Canonical UUIDv4 ledger identity required")

    return value


def read_ledger_identity(db):
    row = db.execute(
        "SELECT value FROM ledger_meta WHERE key=?",
        (IDENTITY_KEY,),
    ).fetchone()

    if row is None:
        return None

    return validate_ledger_identity(row[0])


def initialize_ledger_identity(db):
    """Create identity only inside new-ledger initialization."""

    if not db.in_transaction:
        raise ValueError("Active transaction required")

    existing = read_ledger_identity(db)

    if existing is not None:
        raise ValueError("Ledger identity already exists")

    identity = new_ledger_identity()

    db.execute(
        "INSERT INTO ledger_meta(key,value) VALUES (?,?)",
        (IDENTITY_KEY, identity),
    )

    return identity
