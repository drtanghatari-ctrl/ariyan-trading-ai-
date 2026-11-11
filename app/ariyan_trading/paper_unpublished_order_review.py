"""Match an operator-signed order record to an unpublished paper checkpoint."""

import json
import re

from .accounting import decimal_value
from .ledger_validation import validated_trade
from .paper_pending_diagnostic import inspect_pending_paper_checkpoint

VERSION = "ARIYAN-A063-UNPUBLISHED-ORDER-REVIEW-V1"
ACTION = "REVIEW_UNPUBLISHED_PAPER_ORDER"
DOMAIN = VERSION.encode("ascii") + b"\x00"


def unpublished_order_review_payload(intent):
    """Encode the inspected evidence binding and the independently retained order."""
    if type(intent) is not dict or intent.keys() != {
        "version", "action", "unpublished_order_review_sha256", "expires_at_ms",
        "request_id", "side", "quantity", "price",
    } or intent["version"] != VERSION or intent["action"] != ACTION:
        raise ValueError("Unsupported unpublished order review intent")
    digest = intent["unpublished_order_review_sha256"]
    if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Review intent requires a lowercase evidence SHA-256")
    if type(intent["expires_at_ms"]) is not int or intent["expires_at_ms"] <= 0:
        raise ValueError("Review expiry must be positive UTC epoch milliseconds")
    request_id = intent["request_id"]
    if type(request_id) is not str or not request_id.strip() or len(request_id) > 128:
        raise ValueError("Review requires a valid request ID")
    if type(intent["side"]) is not str or intent["side"] not in ("BUY", "SELL"):
        raise ValueError("Review requires a BUY or SELL side")
    if any(type(intent[field]) is not str or len(intent[field]) > 80
           for field in ("quantity", "price")):
        raise ValueError("Review quantity and price must be decimal strings")
    validated_trade(intent["quantity"], intent["price"])
    return DOMAIN + json.dumps(intent, sort_keys=True, separators=(",", ":")).encode("ascii")


def assess_unpublished_order_review(
    database, anchor, selector, intent, signature, *, expected_state_sha256,
    checkpoint_key, operator_public_key, as_of_ms,
):
    """Reinspect the pending order under FREEZE and assess the signed review."""
    if type(intent) is not dict:
        raise ValueError("Unsupported unpublished order review intent")
    intent = intent.copy()
    payload = unpublished_order_review_payload(intent)
    if type(as_of_ms) is not int or not 0 <= as_of_ms < intent["expires_at_ms"]:
        raise ValueError("Review intent is expired or the clock input is invalid")
    if type(operator_public_key) is not bytes or len(operator_public_key) != 32:
        raise ValueError("Expected an independently supplied raw Ed25519 public key")
    if type(signature) is not bytes or len(signature) != 64:
        raise ValueError("Expected a raw Ed25519 review signature")

    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        Ed25519PublicKey.from_public_bytes(operator_public_key).verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("Invalid operator review signature") from exc

    report = inspect_pending_paper_checkpoint(
        database, anchor, selector, expected_state_sha256=expected_state_sha256,
        key=checkpoint_key, include_unpublished_order=True,
    )
    if report["unpublished_order_review_sha256"] != intent["unpublished_order_review_sha256"]:
        raise ValueError("Review intent differs from the freshly inspected checkpoint")
    order = report["unpublished_order"]
    quantity, price, cost = validated_trade(intent["quantity"], intent["price"])
    if (
        order["request_id"] != intent["request_id"] or order["action"] != intent["side"]
        or decimal_value(order["quantity"]) != quantity or decimal_value(order["price"]) != price
    ):
        raise ValueError("Signed order differs from the freshly inspected order")
    expected_deltas = (cost.copy_negate(), quantity) if intent["side"] == "BUY" else (
        cost, quantity.copy_negate(),
    )
    if (decimal_value(order["cash_delta"]), decimal_value(order["units_delta"])) != expected_deltas:
        raise ValueError("Journal deltas differ from the signed order economics")
    return {
        "version": VERSION,
        "action": ACTION,
        "status": "SIGNED_REVIEW_MATCHES_UNPUBLISHED_PAPER_ORDER",
        "checkpoint_inspection": report,
        "write_authorized": False,
        "live_authorized": False,
    }
