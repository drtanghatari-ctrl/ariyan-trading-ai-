"""Publish a separately authorized pending paper checkpoint under FREEZE."""

import sqlite3
import time
from contextlib import closing
from decimal import Context, localcontext
from pathlib import Path

from .initialization_lock import initialization_lock
from .ledger_validation import replay_ledger_balances
from .paper_pending_diagnostic import _inspect_pending_snapshot, _validated_inputs
from .paper_unpublished_order_review import (
    _order_intent_payload, _require_matching_order, _verify_signed_order,
)
from .trust_anchor import create_anchor, read_anchor, write_anchor

VERSION = "ARIYAN-A064-UNPUBLISHED-PAPER-CHECKPOINT-PUBLICATION-V1"
ACTION = "PUBLISH_UNPUBLISHED_PAPER_CHECKPOINT"
DOMAIN = VERSION.encode("ascii") + b"\x00"


class PaperCheckpointPublicationUncertain(RuntimeError):
    """The anchor write outcome requires inspection."""


def unpublished_checkpoint_publication_payload(intent):
    """Encode the exact order and checkpoint evidence authorized for publication."""
    return _order_intent_payload(intent, version=VERSION, action=ACTION, domain=DOMAIN)


def publish_unpublished_paper_checkpoint(
    database, anchor, selector, intent, signature, *, expected_state_sha256,
    checkpoint_key, operator_public_key,
):
    """Publish and verify the new anchor, leaving the pending marker in place."""
    database, anchor, selector = _validated_inputs(database, anchor, selector, checkpoint_key)
    reserved = {Path(str(database) + suffix) for suffix in ("-wal", "-shm", "-journal", ".init.lock")}
    reserved.add(Path(str(selector) + ".init.lock"))
    with initialization_lock(selector), localcontext(Context(prec=50)):
        if anchor in reserved or anchor.stat().st_nlink != 1:
            raise ValueError("Publication requires a dedicated anchor file")
        with closing(sqlite3.connect(
            database.as_uri() + "?mode=rw", uri=True, isolation_level=None, timeout=10,
        )) as db:
            db.execute("BEGIN IMMEDIATE")
            report, _, opening_cash = _inspect_pending_snapshot(
                db, anchor, selector, expected_state_sha256=expected_state_sha256,
                key=checkpoint_key, include_clearance_binding=False, include_unpublished_order=True,
            )
            signed = _verify_signed_order(
                intent, signature, operator_public_key, time.time_ns() // 1_000_000,
                unpublished_checkpoint_publication_payload,
            )
            _require_matching_order(report, signed)
            replay_ledger_balances(db, opening_cash)
            previous = (report["anchor_sequence"], report["anchor_digest"])
            if read_anchor(anchor, checkpoint_key) != previous:
                raise ValueError("Previous anchor changed before publication")
            tip = (report["journal_sequence"], report["journal_digest"])
            replacement = create_anchor(*tip, checkpoint_key)
            if time.time_ns() // 1_000_000 >= signed["expires_at_ms"]:
                raise ValueError("Publication intent expired before the anchor write")
            try:
                write_anchor(anchor, replacement, checkpoint_key)
                if read_anchor(anchor, checkpoint_key) != tip:
                    raise ValueError("Published anchor readback mismatch")
            except BaseException as exc:
                raise PaperCheckpointPublicationUncertain(
                    "Anchor publication outcome requires inspection before retry or clearance"
                ) from exc
    return {
        "version": VERSION,
        "action": ACTION,
        "status": "PAPER_CHECKPOINT_PUBLISHED_PENDING_CLEARANCE",
        "journal_sequence": tip[0],
        "journal_digest": tip[1],
        "publication_pending": True,
        "paper_state": "FREEZE",
        "live_authorized": False,
    }
