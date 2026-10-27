"""A006-WB02-P3C7 — Pure trust-to-policy consistency checking.

The supplied policy must already have been authenticated and
verified against the local ledger by verify_enrollment().

This module does not authenticate either input, establish
independent authority, prove freshness, or authorize trading.
"""

from ariyan_trading.trust_record_validation import (
    validate_trust_record,
)
from ariyan_trading.writer_policy import (
    VERSION as POLICY_VERSION,
)


def trust_record_matches_policy(record, verified_policy):
    """Fail closed unless trust and verified local policy agree."""

    if not validate_trust_record(record):
        return False

    if type(verified_policy) is not dict:
        return False

    expected_fields = {
        "version",
        "ledger_id",
        "writer_mode",
        "enrollment_sequence",
        "enrollment_digest",
    }

    if set(verified_policy) != expected_fields:
        return False

    if (
        type(verified_policy["version"]) is not str
        or verified_policy["version"] != POLICY_VERSION
    ):
        return False

    if (
        type(verified_policy["writer_mode"]) is not str
        or verified_policy["writer_mode"] != "managed-v1"
    ):
        return False

    if (
        type(verified_policy["ledger_id"]) is not str
        or type(verified_policy["enrollment_sequence"]) is not int
        or type(verified_policy["enrollment_digest"]) is not str
    ):
        return False

    return (
        record.ledger_id == verified_policy["ledger_id"]
        and record.enrollment_sequence
        == verified_policy["enrollment_sequence"]
        and record.enrollment_digest
        == verified_policy["enrollment_digest"]
        and record.writer_policy_version
        == verified_policy["version"]
    )
