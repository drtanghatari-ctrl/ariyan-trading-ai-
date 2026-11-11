"""Inspect paper checkpoint recovery under an authenticated FREEZE."""

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from decimal import Context, localcontext
from pathlib import Path

from .checkpoint_coordinator import PENDING
from .checkpoint_diagnostic import _input_path
from .initialization_lock import initialization_lock
from .journal_store import verify_protected_journal
from .ledger_identity import read_ledger_identity
from .ledger_validation import exact_cash, replay_ledger_balances
from .paper_active_selection import read_paper_active_selection
from .paper_execution_state import read_paper_execution_state
from .schema_validation import validate_ledger_schema
from .trust_anchor import read_anchor

VERSION = "ARIYAN-A058-PAPER-PENDING-DIAGNOSTIC-V1"
RECOVERY_STATUS_VERSION = "ARIYAN-A066-PAPER-CHECKPOINT-RECOVERY-STATUS-V1"
PENDING_STATUS = {
    "AT_VERIFIED_JOURNAL_TIP": "PENDING_AT_PUBLISHED_TIP",
    "AT_PREVIOUS_VERIFIED_TIP": "PENDING_AT_PREVIOUS_TIP",
    "OUTSIDE_EXPECTED_TIPS": "PENDING_WITH_DIVERGENT_ANCHOR",
}


def _validated_inputs(database, anchor, selector, key):
    database, anchor, selector = map(_input_path, (database, anchor, selector))
    if database.samefile(anchor) or database.samefile(selector) or anchor.samefile(selector):
        raise ValueError("Database, anchor and selector must be separate files")
    if type(key) is not bytes or not 32 <= len(key) <= 4096:
        raise ValueError("Checkpoint key must contain 32..4096 raw bytes")
    return database, anchor, selector


def inspect_pending_paper_checkpoint(database, anchor, selector, *, expected_state_sha256, key,
                                     include_clearance_binding=False, include_unpublished_order=False,
                                     recovery_status=False):
    """Classify the anchor under FREEZE, optionally allowing an absent pending marker."""
    if recovery_status and (include_clearance_binding or include_unpublished_order):
        raise ValueError("Recovery status must be requested separately from signing evidence")
    database, anchor, selector = _validated_inputs(database, anchor, selector, key)
    with initialization_lock(selector), localcontext(Context(prec=50)):
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            db.execute("BEGIN")
            report, _, _ = _inspect_pending_snapshot(
                db, anchor, selector, expected_state_sha256=expected_state_sha256,
                key=key, include_clearance_binding=include_clearance_binding,
                include_unpublished_order=include_unpublished_order,
                recovery_status=recovery_status,
            )
    return report


def _inspect_pending_snapshot(db, anchor, selector, *, expected_state_sha256, key,
                              include_clearance_binding, include_unpublished_order=False,
                              recovery_status=False):
    """Inspect inside the caller's transaction and selector lock."""
    validate_ledger_schema(db)
    identity = read_ledger_identity(db)
    state_path, pin = read_paper_active_selection(selector, identity, key=key)
    if type(expected_state_sha256) is not str or pin != expected_state_sha256:
        raise ValueError("Active selection differs from the independently retained pin")
    if read_paper_execution_state(state_path, identity, key=key, expected_sha256=pin) != "FREEZE":
        raise ValueError("Pending checkpoint inspection requires FREEZE")

    marker = db.execute("SELECT value FROM ledger_meta WHERE key=?", (PENDING,)).fetchone()
    if marker is None and not recovery_status:
        raise ValueError("Expected a coordinator pending publication marker")
    if marker is not None and not re.fullmatch(r"[0-9a-f]{32}", marker[0]):
        raise ValueError("Expected a coordinator pending publication marker")
    opening = db.execute(
        "SELECT value FROM ledger_meta WHERE key='opening_cash'"
    ).fetchone()
    if opening is None:
        raise ValueError("Ledger is missing opening cash")
    opening_cash = exact_cash(opening[0])
    tip_digest = verify_protected_journal(db, opening_cash)
    tip_sequence = db.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
    if marker is not None and tip_sequence == 0:
        raise ValueError("Pending publication requires a committed entry")

    anchor_tip = read_anchor(anchor, key)
    position = "AT_VERIFIED_JOURNAL_TIP"
    if anchor_tip != (tip_sequence, tip_digest):
        if marker is None:
            raise ValueError("Anchor differs from the journal tip with no pending marker")
        if tip_sequence == 1:
            prior_digest = db.execute(
                "SELECT value FROM ledger_meta WHERE key='journal_genesis'"
            ).fetchone()[0]
        else:
            prior_digest = db.execute(
                "SELECT digest FROM journal_commitments WHERE sequence=?", (tip_sequence - 1,),
            ).fetchone()[0]
        position = (
            "AT_PREVIOUS_VERIFIED_TIP" if anchor_tip == (tip_sequence - 1, prior_digest)
            else "OUTSIDE_EXPECTED_TIPS"
        )

    report = {
        "version": VERSION,
        "paper_state": "FREEZE",
        "publication_pending": marker is not None,
        "journal_sequence": tip_sequence,
        "journal_digest": tip_digest,
        "anchor_sequence": anchor_tip[0],
        "anchor_digest": anchor_tip[1],
        "anchor_position": position,
        "repair_authorized": False,
        "write_authorized": False,
        "live_authorized": False,
    }
    if recovery_status:
        report["version"] = RECOVERY_STATUS_VERSION
        if marker is None:
            replay_ledger_balances(db, opening_cash)
            report["status"] = "NO_PENDING_VERIFIED_TIP"
        else:
            report["status"] = PENDING_STATUS[position]
    if include_clearance_binding or include_unpublished_order:
        binding = {
            "version": "ARIYAN-A059-PAPER-CLEARANCE-BINDING-V1",
            "ledger_identity": identity,
            "active_state_sha256": pin,
            "pending_attempt": marker[0],
            "journal_sequence": tip_sequence,
            "journal_digest": tip_digest,
            "anchor_sequence": anchor_tip[0],
            "anchor_digest": anchor_tip[1],
            "anchor_position": position,
        }
        encoded = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("ascii")
        if include_clearance_binding:
            report["clearance_binding_sha256"] = hashlib.sha256(encoded).hexdigest()
        if include_unpublished_order:
            if position != "AT_PREVIOUS_VERIFIED_TIP":
                raise ValueError("Unpublished order review requires the previous verified anchor")
            fields = ("request_id", "action", "quantity", "price", "cash_delta", "units_delta")
            row = db.execute(
                "SELECT request_id,action,quantity,price,cash_delta,units_delta "
                "FROM ledger_entries WHERE sequence=?", (tip_sequence,),
            ).fetchone()
            report["unpublished_order"] = {
                **dict(zip(fields, row, strict=True)),
                "authenticated_by_anchor": False,
            }
            report["unpublished_order_review_sha256"] = hashlib.sha256(
                b"ARIYAN-A063-UNPUBLISHED-ORDER-REVIEW-BINDING-V1\x00" + encoded
            ).hexdigest()
    return report, marker[0] if marker is not None else None, opening_cash


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--anchor", required=True, type=Path)
    parser.add_argument("--selector", required=True, type=Path)
    parser.add_argument("--expected-state-sha256", required=True)
    parser.add_argument("--checkpoint-key-file", required=True, type=Path)
    parser.add_argument("--include-clearance-binding", action="store_true",
                        help="Include the fingerprint for an A059 approval")
    parser.add_argument("--include-unpublished-order", action="store_true",
                        help="Show the pending order when the anchor is one verified entry behind")
    parser.add_argument("--recovery-status", action="store_true",
                        help="Check recovery status even if the pending marker is absent")
    args = parser.parse_args(argv)
    try:
        key_path = _input_path(args.checkpoint_key_file)
        if any(key_path.samefile(_input_path(path))
               for path in (args.database, args.anchor, args.selector)):
            raise ValueError("Key file must be separate from inspection inputs")
        with key_path.open("rb") as stream:
            key = stream.read(4097)
        report = inspect_pending_paper_checkpoint(
            args.database, args.anchor, args.selector,
            expected_state_sha256=args.expected_state_sha256, key=key,
            include_clearance_binding=args.include_clearance_binding,
            include_unpublished_order=args.include_unpublished_order,
            recovery_status=args.recovery_status,
        )
    except (OSError, ValueError, TypeError, ArithmeticError, sqlite3.Error):
        parser.exit(2, "Pending checkpoint inspection rejected; no repair performed.\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
