"""A006 P3C12-B6C3C2A: authorization-status history entry.

Immutable structural contract and deterministic encoding only.

No authentication, durable storage, trusted sequence floor,
rollback resistance, or trading authorization.
"""

import json
from dataclasses import dataclass

from ariyan_trading.authorization_status_observation import (
    AuthorizationStatusObservation,
    validate_authorization_status_observation,
)
from ariyan_trading.authorization_validation import valid_uuid


VERSION = "ARIYAN-A006-AUTH-STATUS-HISTORY-ENTRY-V1"
DOMAIN = b"ARIYAN-A006-AUTH-STATUS-HISTORY-ENTRY-V1\x00"


@dataclass(frozen=True)
class AuthorizationStatusHistoryEntry:
    version: str
    stream_id: str
    history_sequence: int
    observation: AuthorizationStatusObservation


def validate_status_history_entry(entry):
    """Validate structure only; never establish authority."""

    if type(entry) is not AuthorizationStatusHistoryEntry:
        return False

    return (
        type(entry.version) is str
        and entry.version == VERSION
        and valid_uuid(entry.stream_id)
        and type(entry.history_sequence) is int
        and entry.history_sequence >= 1
        and validate_authorization_status_observation(
            entry.observation
        )
    )


def canonical_status_history_entry(entry):
    """Return domain-separated canonical bytes for a valid entry."""

    if not validate_status_history_entry(entry):
        raise ValueError("Invalid authorization status history entry")

    observation = entry.observation
    status = observation.status_record

    payload = {
        "version": entry.version,
        "stream_id": entry.stream_id,
        "history_sequence": entry.history_sequence,
        "observation": {
            "version": observation.version,
            "source_id": observation.source_id,
            "sequence": observation.sequence,
            "observed_at": observation.observed_at,
            "valid_until": observation.valid_until,
            "status_record": {
                "authorization_id": status.authorization_id,
                "authority_id": status.authority_id,
                "revision": status.revision,
                "status": status.status.value,
            },
        },
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")

    return DOMAIN + encoded
