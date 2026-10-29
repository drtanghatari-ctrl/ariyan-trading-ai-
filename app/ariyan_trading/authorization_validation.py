"""A006 B4: structural validation only; grants no authority."""

import uuid
from ariyan_trading.authorization_evidence import (
    AUTHORIZATION_EVIDENCE_VERSION,
    AuthorizationEvidence,
)

OPERATIONS = frozenset(("BUY", "SELL"))


def valid_uuid(value):
    if type(value) is not str:
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value


def valid_name(value):
    if type(value) is not str:
        return False
    if not value or value != value.strip():
        return False
    try:
        encoded = value.encode("utf-8")
    except UnicodeError:
        return False
    return (
        len(encoded) <= 128
        and all(ord(c) >= 32 and ord(c) != 127 for c in value)
    )


def validate_authorization_evidence(e):
    """Check structure, never authenticity or permission."""
    if type(e) is not AuthorizationEvidence:
        return False
    if type(e.version) is not str or e.version != AUTHORIZATION_EVIDENCE_VERSION:
        return False
    if not valid_uuid(e.authorization_id):
        return False
    if not valid_uuid(e.ledger_id):
        return False
    if not valid_name(e.writer_id):
        return False
    if not valid_name(e.authority_id):
        return False
    if type(e.revision) is not int or e.revision <= 0:
        return False

    ops = e.allowed_operations
    if type(ops) is not tuple or not ops:
        return False
    if len(ops) > len(OPERATIONS):
        return False
    if any(type(op) is not str or op not in OPERATIONS for op in ops):
        return False
    if len(set(ops)) != len(ops):
        return False

    if type(e.valid_from) is not int:
        return False
    if type(e.valid_until) is not int:
        return False
    return 0 <= e.valid_from < e.valid_until
