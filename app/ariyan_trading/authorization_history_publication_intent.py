"""A006 C2D-04B2A authorization-history publication intent.

Pure validation and canonical serialization.

No persistence, publication, recovery, freshness guarantee,
financial mutation, or trading authorization.
"""

import json

from ariyan_trading.authorization_validation import valid_uuid

VERSION = "ARIYAN-A006-AUTH-HISTORY-PUBINTENT-V1"

FIELDS = frozenset({
    "version",
    "stream_id",
    "history_sequence",
    "history_digest",
})


def validate_publication_intent(intent):
    """Validate an exact, canonical publication-intent object."""

    if type(intent) is not dict:
        raise ValueError("Publication intent must be a dictionary")

    if set(intent) != FIELDS:
        raise ValueError("Invalid publication-intent fields")

    if intent["version"] != VERSION:
        raise ValueError("Unsupported publication-intent version")

    if not valid_uuid(intent["stream_id"]):
        raise ValueError("Invalid publication-intent stream")

    sequence = intent["history_sequence"]

    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid publication-intent sequence")

    digest = intent["history_digest"]

    if type(digest) is not str or len(digest) != 64:
        raise ValueError("Invalid publication-intent digest")

    try:
        raw = bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError("Invalid publication-intent digest") from exc

    if len(raw) != 32 or raw.hex() != digest:
        raise ValueError("Noncanonical publication-intent digest")

    return True


def create_publication_intent(stream_id, sequence, digest):
    """Create a validated publication-intent object."""

    intent = {
        "version": VERSION,
        "stream_id": stream_id,
        "history_sequence": sequence,
        "history_digest": digest,
    }

    validate_publication_intent(intent)

    return intent


def canonical_publication_intent(intent):
    """Return deterministic ASCII-encoded publication intent."""

    validate_publication_intent(intent)

    return json.dumps(
        intent,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
