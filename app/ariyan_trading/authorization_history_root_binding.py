"""A006 B4-B2B: immutable human-root public-key binding evidence.

Structural validation only. No trusted enrollment, signature
verification, key generation, key custody, revocation, freshness,
writer admission, database mutation or trading authorization.
"""

import re
from dataclasses import dataclass

from .authorization_validation import valid_name


VERSION = "ARIYAN-A006-HISTORY-ROOT-BINDING-V1"
ALGORITHM = "Ed25519"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class HistoryRootBinding:
    version: str
    root_authority_id: str
    algorithm: str
    public_key_sha256: str
    enrollment_revision: int
    trust_reference: str


def validate_history_root_binding(record):
    """Validate shape only; never declare a root trusted."""

    if type(record) is not HistoryRootBinding:
        return False

    if type(record.version) is not str or record.version != VERSION:
        return False

    if not valid_name(record.root_authority_id):
        return False

    if type(record.algorithm) is not str or record.algorithm != ALGORITHM:
        return False

    if (
        type(record.public_key_sha256) is not str
        or _SHA256.fullmatch(record.public_key_sha256) is None
    ):
        return False

    if (
        type(record.enrollment_revision) is not int
        or record.enrollment_revision <= 0
    ):
        return False

    if not valid_name(record.trust_reference):
        return False

    return True
