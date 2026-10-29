"""A006 P3C12-B6C3C2C1: strict authorization-history decoder.

Canonical decoding and structural validation only.

No authentication, trusted freshness, rollback resistance,
database mutation, or trading authorization.
"""

import json

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    AuthorizationStatusObservation,
)
from ariyan_trading.authorization_status_history import (
    DOMAIN,
    AuthorizationStatusHistoryEntry,
    canonical_status_history_entry,
    validate_status_history_entry,
)


MAX_PAYLOAD_BYTES = 8192

ENTRY_FIELDS = frozenset({
    "version",
    "stream_id",
    "history_sequence",
    "observation",
})

OBSERVATION_FIELDS = frozenset({
    "version",
    "source_id",
    "sequence",
    "observed_at",
    "valid_until",
    "status_record",
})

STATUS_FIELDS = frozenset({
    "authorization_id",
    "authority_id",
    "revision",
    "status",
})


def _unique_object(pairs):
    """Reject duplicate JSON object keys."""

    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value

    return result


def _exact_fields(value, expected):
    if type(value) is not dict or set(value) != expected:
        raise ValueError("Invalid history object fields")


def _reject_constant(value):
    raise ValueError("Nonstandard JSON constant")


def decode_status_history_entry(payload):
    """Decode only exact canonical history-entry bytes."""

    if type(payload) is not bytes:
        raise ValueError("History payload must be bytes")

    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("History payload exceeds size limit")

    if not payload.startswith(DOMAIN):
        raise ValueError("Invalid history payload domain")

    encoded = payload[len(DOMAIN):]

    if not encoded:
        raise ValueError("Empty history payload")

    try:
        record = json.loads(
            encoded.decode("ascii"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, TypeError) as exc:
        raise ValueError("Invalid history JSON") from exc

    _exact_fields(record, ENTRY_FIELDS)

    observation_data = record["observation"]
    _exact_fields(observation_data, OBSERVATION_FIELDS)

    status_data = observation_data["status_record"]
    _exact_fields(status_data, STATUS_FIELDS)

    status_value = status_data["status"]

    if type(status_value) is not str:
        raise ValueError("Invalid authorization status type")

    try:
        status = AuthorizationStatus(status_value)
    except ValueError as exc:
        raise ValueError("Unknown authorization status") from exc

    status_record = AuthorizationStatusRecord(
        authorization_id=status_data["authorization_id"],
        authority_id=status_data["authority_id"],
        revision=status_data["revision"],
        status=status,
    )

    observation = AuthorizationStatusObservation(
        version=observation_data["version"],
        status_record=status_record,
        source_id=observation_data["source_id"],
        sequence=observation_data["sequence"],
        observed_at=observation_data["observed_at"],
        valid_until=observation_data["valid_until"],
    )

    entry = AuthorizationStatusHistoryEntry(
        version=record["version"],
        stream_id=record["stream_id"],
        history_sequence=record["history_sequence"],
        observation=observation,
    )

    if not validate_status_history_entry(entry):
        raise ValueError("Invalid reconstructed history entry")

    if canonical_status_history_entry(entry) != payload:
        raise ValueError("Noncanonical history encoding")

    return entry
