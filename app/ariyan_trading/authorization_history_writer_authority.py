"""A006 C2D-04B2C4B4-A: immutable history writer authority evidence.

Structural evidence only.

No authentication, credential issuance, trusted clock, revocation
lookup, SQLite mutation, writer admission, or trading authorization.
"""

from dataclasses import dataclass

from .authorization_validation import valid_uuid, valid_name


VERSION = "ARIYAN-A006-HISTORY-WRITER-AUTHORITY-V1"
APPEND_HISTORY = "APPEND_HISTORY"


@dataclass(frozen=True)
class HistoryWriterAuthorityEvidence:
    version: str
    authorization_id: str
    root_authority_id: str
    writer_id: str
    stream_id: str
    revision: int
    allowed_operations: tuple[str, ...]
    valid_from: int
    valid_until: int
    status_reference: str


def validate_history_writer_authority_evidence(record):
    """Validate structure only; never establish authority."""

    if type(record) is not HistoryWriterAuthorityEvidence:
        return False

    if record.version != VERSION:
        return False

    if not valid_uuid(record.authorization_id):
        return False

    if not valid_uuid(record.stream_id):
        return False

    if not valid_name(record.root_authority_id):
        return False

    if not valid_name(record.writer_id):
        return False

    if type(record.revision) is not int or record.revision <= 0:
        return False

    operations = record.allowed_operations

    if type(operations) is not tuple or not operations:
        return False

    if len(operations) != len(set(operations)):
        return False

    if any(
        type(operation) is not str or operation != APPEND_HISTORY
        for operation in operations
    ):
        return False

    if type(record.valid_from) is not int:
        return False

    if type(record.valid_until) is not int:
        return False

    if record.valid_from < 0:
        return False

    if record.valid_until <= record.valid_from:
        return False

    if not valid_name(record.status_reference):
        return False

    return True
