"""A006 B5: canonical authorization evidence encoding only."""

import json

from ariyan_trading.authorization_validation import (
    validate_authorization_evidence,
)

VERSION = "ARIYAN-A006-AUTHORIZATION-MAC-V1"
DOMAIN = b"ARIYAN-A006-AUTHORIZATION-MAC-V1\x00"


def canonical_authorization_payload(evidence):
    """Encode valid evidence; never grant authorization."""

    if not validate_authorization_evidence(evidence):
        raise ValueError("Invalid authorization evidence")

    record = {
        "version": VERSION,
        "evidence_version": evidence.version,
        "authorization_id": evidence.authorization_id,
        "ledger_id": evidence.ledger_id,
        "writer_id": evidence.writer_id,
        "authority_id": evidence.authority_id,
        "revision": evidence.revision,
        "allowed_operations": sorted(evidence.allowed_operations),
        "valid_from": evidence.valid_from,
        "valid_until": evidence.valid_until,
    }

    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return DOMAIN + encoded
