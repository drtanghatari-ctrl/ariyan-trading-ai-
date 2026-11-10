"""Assess or apply signed pending-marker clearance for a published paper checkpoint."""

import json
import re
import sqlite3
import time
from contextlib import closing
from decimal import Context, localcontext

from .checkpoint_coordinator import PENDING
from .checkpoint_verifier import verify_checkpoint
from .initialization_lock import initialization_lock
from .paper_pending_diagnostic import (
    _inspect_pending_snapshot, _validated_inputs, inspect_pending_paper_checkpoint,
)

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


class PendingClearanceUncertain(RuntimeError):
    """The marker-clearance commit outcome requires inspection."""


def _verify_signed_intent(intent, signature, operator_public_key, as_of_ms):
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
    return intent


def _require_matching_clearance(report, intent):
    if report["anchor_position"] != "AT_VERIFIED_JOURNAL_TIP":
        raise ValueError("Clearance assessment requires an anchor at the current journal tip")
    if report["clearance_binding_sha256"] != intent["clearance_binding_sha256"]:
        raise ValueError("Clearance intent differs from the freshly inspected checkpoint")


def assess_pending_clearance(
    database, anchor, selector, intent, signature, *, expected_state_sha256,
    checkpoint_key, operator_public_key, as_of_ms,
):
    """Reinspect and match a signed approval without granting write authority."""
    intent = _verify_signed_intent(intent, signature, operator_public_key, as_of_ms)
    report = inspect_pending_paper_checkpoint(
        database, anchor, selector, expected_state_sha256=expected_state_sha256,
        key=checkpoint_key, include_clearance_binding=True,
    )
    _require_matching_clearance(report, intent)
    return {
        "version": VERSION,
        "action": ACTION,
        "status": "SIGNED_APPROVAL_MATCHES_INSPECTED_PENDING_CHECKPOINT",
        "checkpoint_inspection": report,
        "write_authorized": False,
    }


def clear_published_pending_marker(
    database, anchor, selector, intent, signature, *, expected_state_sha256,
    checkpoint_key, operator_public_key,
):
    """Clear one signed, already-published pending marker under paper FREEZE."""
    database, anchor, selector = _validated_inputs(database, anchor, selector, checkpoint_key)
    with initialization_lock(selector), localcontext(Context(prec=50)):
        with closing(sqlite3.connect(
            database.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=10,
        )) as db:
            if db.execute("PRAGMA synchronous").fetchone()[0] not in (2, 3):
                raise ValueError("SQLite FULL or EXTRA synchronous mode required")
            db.execute("BEGIN IMMEDIATE")
            report, marker, opening_cash = _inspect_pending_snapshot(
                db, anchor, selector, expected_state_sha256=expected_state_sha256,
                key=checkpoint_key, include_clearance_binding=True,
            )
            signed = _verify_signed_intent(
                intent, signature, operator_public_key, time.time_ns() // 1_000_000,
            )
            _require_matching_clearance(report, signed)

            deleted = db.execute(
                "DELETE FROM ledger_meta WHERE key=? AND value=?", (PENDING, marker),
            )
            if deleted.rowcount != 1 or db.total_changes != 1:
                raise ValueError("Pending clearance must change only the inspected marker")
            tip = verify_checkpoint(db, opening_cash, anchor, checkpoint_key)
            if tip != (report["journal_sequence"], report["journal_digest"]):
                raise ValueError("Checkpoint changed during pending clearance")
            try:
                db.execute("COMMIT")
            except BaseException as exc:
                raise PendingClearanceUncertain(
                    "Clearance commit outcome requires inspection; do not retry automatically"
                ) from exc
    return {
        "version": "ARIYAN-A060-PAPER-PENDING-CLEARANCE-RESULT-V1",
        "status": "PUBLISHED_PENDING_MARKER_CLEARED",
        "journal_sequence": tip[0],
        "journal_digest": tip[1],
        "clearance_binding_sha256": signed["clearance_binding_sha256"],
        "paper_state": "FREEZE",
        "live_authorized": False,
    }
