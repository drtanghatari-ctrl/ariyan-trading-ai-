"""Assess a signed approval for a published paper checkpoint's pending marker."""

import json
import re

from .paper_pending_diagnostic import inspect_pending_paper_checkpoint

VERSION = "ARIYAN-A059-PAPER-PENDING-CLEARANCE-V1"
ACTION = "CLEAR_PUBLISHED_PENDING_MARKER"
DOMAIN = VERSION.encode("ascii") + b"\x00"


def clearance_payload(intent):
    """Encode the exact fields signed by the paper recovery operator."""
    if type(intent) is not dict or intent.keys() != {
        "version", "action", "clearance_binding_sha256", "expires_at_ms",
    } or intent["version"] != VERSION or intent["action"] != ACTION:
        raise ValueError("Unsupported pending clearance intent")
    digest = intent["clearance_binding_sha256"]
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Clearance intent requires a lowercase evidence SHA-256")
    if type(intent["expires_at_ms"]) is not int or intent["expires_at_ms"] <= 0:
        raise ValueError("Clearance expiry must be positive UTC epoch milliseconds")
    return DOMAIN + json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("ascii")


def assess_pending_clearance(
    database, anchor, selector, intent, signature, *, expected_state_sha256,
    checkpoint_key, operator_public_key, as_of_ms,
):
    """Reinspect and match a signed approval without granting write authority."""
    if type(intent) is not dict:
        raise ValueError("Unsupported pending clearance intent")
    intent = intent.copy()
    payload = clearance_payload(intent)
    if type(as_of_ms) is not int or not 0 <= as_of_ms < intent["expires_at_ms"]:
        raise ValueError("Clearance intent is expired or the clock input is invalid")
    if type(operator_public_key) is not bytes or len(operator_public_key) != 32:
        raise ValueError("Expected an independently supplied raw Ed25519 public key")
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError("Expected a raw Ed25519 clearance signature")

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(operator_public_key).verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("Invalid operator clearance signature") from exc

    report = inspect_pending_paper_checkpoint(
        database, anchor, selector, expected_state_sha256=expected_state_sha256,
        key=checkpoint_key, include_clearance_binding=True,
    )
    if report["anchor_position"] != "AT_VERIFIED_JOURNAL_TIP":
        raise ValueError("Clearance assessment requires an anchor at the current journal tip")
    if report["clearance_binding_sha256"] != intent["clearance_binding_sha256"]:
        raise ValueError("Clearance intent differs from the freshly inspected checkpoint")
    return {
        "version": VERSION,
        "action": ACTION,
        "status": "SIGNED_APPROVAL_MATCHES_INSPECTED_PENDING_CHECKPOINT",
        "checkpoint_inspection": report,
        "write_authorized": False,
    }
