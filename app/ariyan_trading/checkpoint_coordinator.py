"""A006 experimental paper-trade checkpoint coordinator.

No broker connectivity, automatic enrollment, or recovery.
The caller owns the ledger connection and must not share it concurrently.
"""

from decimal import localcontext
from pathlib import Path
from uuid import uuid4

from .checkpoint_publication import (
    PublicationEvent as Event,
    PublicationState as State,
    advance_publication,
)
from .checkpoint_verifier import verify_checkpoint
from .journal_store import append_journal_commitment, verify_protected_journal
from .ledger_validation import validated_trade
from .trust_anchor import create_anchor, read_anchor, write_anchor

PENDING = "checkpoint_publication_pending"


class PublicationUncertain(RuntimeError):
    """A commit was attempted; inspect evidence before any further action."""


def _tip(ledger):
    digest = verify_protected_journal(ledger.db, ledger.opening_cash)
    sequence = ledger.db.execute(
        "SELECT COUNT(*) FROM ledger_entries"
    ).fetchone()[0]
    return sequence, digest


def execute_checkpointed_trade(
    ledger, action, request_id, quantity, price, *, anchor_path, key
):
    """Commit one explicit paper trade and publish its authenticated tip.

    Missing, stale, invalid, or pending checkpoints are rejected.
    A committed trade is never retried or reversed automatically.
    """
    db = ledger.db
    if ledger.checkpoint_read_only:
        raise RuntimeError("Checkpoint-verified ledger is read-only")
    if db.in_transaction:
        raise ValueError("Coordinator requires an idle connection")
    if action not in ("BUY", "SELL"):
        raise ValueError("Only explicit BUY or SELL is supported")
    if (
        not isinstance(request_id, str)
        or not request_id.strip()
        or len(request_id) > 128
    ):
        raise ValueError("Invalid request ID")

    quantity, price, cost = validated_trade(quantity, price)
    anchor = Path(anchor_path).resolve()
    database = ledger.path.resolve()
    reserved = {
        database,
        Path(str(database) + "-wal"),
        Path(str(database) + "-shm"),
        Path(str(database) + "-journal"),
        Path(str(database) + ".init.lock"),
    }
    if anchor in reserved:
        raise ValueError("Anchor must be separate from ledger files")
    if anchor.exists():
        for path in reserved:
            if path.exists() and anchor.samefile(path):
                raise ValueError("Anchor aliases a ledger file")

    # FULL or EXTRA synchronization is required for committed evidence.
    if db.execute("PRAGMA synchronous").fetchone()[0] not in (2, 3):
        raise ValueError("SQLite FULL or EXTRA synchronous mode required")

    state = State.READY
    attempt = uuid4().hex
    commit_attempted = False

    try:
        db.execute("BEGIN IMMEDIATE")
        previous = verify_checkpoint(
            db, ledger.opening_cash, anchor, key
        )
        cash, units = ledger.balances()
        if action == "BUY" and cost > cash:
            raise ValueError("Insufficient cash")
        if action == "SELL" and quantity > units:
            raise ValueError("Insufficient units")

        with localcontext() as ctx:
            ctx.prec = 50
            cash_delta = -cost if action == "BUY" else cost
            units_delta = quantity if action == "BUY" else -quantity

        db.execute(
            "INSERT INTO ledger_entries "
            "(request_id,action,quantity,price,cash_delta,units_delta) "
            "VALUES (?,?,?,?,?,?)",
            (request_id, action, str(quantity), str(price),
             str(cash_delta), str(units_delta)),
        )
        append_journal_commitment(db, ledger.opening_cash)
        expected = _tip(ledger)
        balances = ledger.balances()
        db.execute(
            "INSERT INTO ledger_meta(key,value) VALUES (?,?)",
            (PENDING, attempt),
        )
        commit_attempted = True
        db.execute("COMMIT")
        state = advance_publication(state, Event.COMMIT_CONFIRMED)
    except BaseException as exc:
        if db.in_transaction:
            db.rollback()
        if commit_attempted:
            raise PublicationUncertain(
                "Database commit outcome requires inspection; do not retry"
            ) from exc
        raise

    try:
        # Reacquire the writer lock and detect intervening changes.
        # Hold it through publication and marker clearance.
        db.execute("BEGIN IMMEDIATE")
        if _tip(ledger) != expected:
            raise ValueError("Journal changed before publication")
        if read_anchor(anchor, key) != previous:
            raise ValueError("Anchor changed before publication")
        marker = db.execute(
            "SELECT value FROM ledger_meta WHERE key=?", (PENDING,)
        ).fetchone()
        if marker != (attempt,):
            raise ValueError("Publication attempt marker changed")

        state = advance_publication(state, Event.PUBLICATION_STARTED)
        write_anchor(
            anchor, create_anchor(*expected, key), key
        )
        if read_anchor(anchor, key) != expected:
            raise ValueError("Published anchor readback mismatch")

        db.execute(
            "DELETE FROM ledger_meta WHERE key=? AND value=?",
            (PENDING, attempt),
        )
        db.execute("COMMIT")
        state = advance_publication(state, Event.PUBLICATION_DURABLE)
        return {
            "state": state,
            "sequence": expected[0],
            "digest": expected[1],
            "cash": balances[0],
            "units": balances[1],
        }
    except BaseException as exc:
        if db.in_transaction:
            db.rollback()
        raise PublicationUncertain(
            "Trade committed; publication outcome requires inspection; "
            "do not retry or re-anchor"
        ) from exc
