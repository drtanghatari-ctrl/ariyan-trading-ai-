"""Prepare an offline paper state from an operator-signed escalation."""

import json
import re

from .ledger_identity import validate_ledger_identity
from .paper_execution_state import (
    PAPER_EXECUTION_STATES, create_pinned_paper_execution_state, read_paper_execution_state,
)

VERSION = "ARIYAN-A052-PAPER-STATE-ESCALATION-V1"
DOMAIN = VERSION.encode("ascii") + b"\x00"


def escalation_payload(intent):
    """Encode exactly the fields the independent operator signs."""
    if type(intent) is not dict or intent.keys() != {
        "version", "ledger_identity", "current_state_sha256", "target_state", "expires_at_ms",
    } or intent["version"] != VERSION:
        raise ValueError("Unsupported paper escalation intent")
    validate_ledger_identity(intent["ledger_identity"])
    pin = intent["current_state_sha256"]
    if type(pin) is not str or not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise ValueError("Escalation requires a lowercase current-state SHA-256")
    if type(intent["target_state"]) is not str or intent["target_state"] not in ("STOP", "FREEZE"):
        raise ValueError("Escalation target must be STOP or FREEZE")
    if type(intent["expires_at_ms"]) is not int or intent["expires_at_ms"] <= 0:
        raise ValueError("Escalation expiry must be positive UTC epoch milliseconds")
    return DOMAIN + json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("ascii")


def prepare_paper_escalation(
    current_path, next_path, intent, signature, *, ledger_identity, expected_current_sha256,
    checkpoint_key, operator_public_key, as_of_ms,
):
    """Create an authenticated successor and return its pin without activating it."""
    if type(intent) is not dict:
        raise ValueError("Unsupported paper escalation intent")
    intent = intent.copy()
    payload = escalation_payload(intent)
    if intent["ledger_identity"] != ledger_identity:
        raise ValueError("Escalation intent refers to a different ledger")
    if intent["current_state_sha256"] != expected_current_sha256:
        raise ValueError("Escalation intent does not match the independently retained pin")
    if type(as_of_ms) is not int or not 0 <= as_of_ms < intent["expires_at_ms"]:
        raise ValueError("Escalation intent is expired or the clock input is invalid")
    if type(operator_public_key) is not bytes or len(operator_public_key) != 32:
        raise ValueError("Expected an independently supplied raw Ed25519 public key")
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError("Expected a raw Ed25519 escalation signature")

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(operator_public_key).verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("Invalid operator escalation signature") from exc

    current = read_paper_execution_state(
        current_path, ledger_identity, key=checkpoint_key, expected_sha256=expected_current_sha256,
    )
    target = intent["target_state"]
    if PAPER_EXECUTION_STATES.index(target) <= PAPER_EXECUTION_STATES.index(current):
        raise ValueError("Target must be more restrictive than the current paper state")
    return create_pinned_paper_execution_state(next_path, ledger_identity, target, key=checkpoint_key)
