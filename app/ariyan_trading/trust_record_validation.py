"""A006-WB02-P3C5 — Pure trust-record structural validation.

No authentication, freshness proof, storage, or authorization.
"""

import re
import uuid

from ariyan_trading.trust_authority import TrustRecord
from ariyan_trading.writer_policy import VERSION as POLICY_VERSION


TRUST_RECORD_VERSION = "ARIYAN-A006-TRUST-RECORD-V1"

_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")


def validate_trust_record(record: TrustRecord) -> bool:
    """Return True only for structurally valid trust records.

    Structural validity does not establish authenticity,
    freshness, authority independence, or enrollment.
    """

    if not isinstance(record, TrustRecord):
        return False

    if type(record.ledger_id) is not str:
        return False

    try:
        parsed = uuid.UUID(record.ledger_id)
    except (ValueError, AttributeError, TypeError):
        return False

    if parsed.version != 4 or str(parsed) != record.ledger_id:
        return False

    if (
        type(record.enrollment_sequence) is not int
        or record.enrollment_sequence < 0
    ):
        return False

    if (
        type(record.enrollment_digest) is not str
        or _DIGEST_RE.fullmatch(record.enrollment_digest) is None
    ):
        return False

    if (
        type(record.writer_policy_version) is not str
        or record.writer_policy_version != POLICY_VERSION
    ):
        return False

    if type(record.authority_id) is not str:
        return False

    if not record.authority_id or record.authority_id.strip() != record.authority_id:
        return False

    try:
        authority_bytes = record.authority_id.encode("utf-8")
    except UnicodeEncodeError:
        return False

    if not (1 <= len(authority_bytes) <= 128):
        return False

    if any(ord(character) < 32 or ord(character) == 127
           for character in record.authority_id):
        return False

    if type(record.revision) is not int or record.revision <= 0:
        return False

    if (
        type(record.record_version) is not str
        or record.record_version != TRUST_RECORD_VERSION
    ):
        return False

    return True
