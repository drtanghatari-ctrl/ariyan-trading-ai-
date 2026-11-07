"""A020 read-only checkpoint boundary inspection; no enrollment or trade authority."""

import argparse
import json
import sqlite3
from decimal import Context, localcontext
from pathlib import Path

from .checkpoint_verifier import verify_checkpoint
from .durable_ledger import DurableLedger
from .ledger_identity import read_ledger_identity
from .ledger_validation import exact_cash
from .schema_validation import validate_ledger_schema


def _input_path(value):
    path = Path(value).expanduser().absolute()
    if path.resolve(strict=True) != path or not path.is_file():
        raise ValueError("Input must be an existing regular file without symlink components")
    return path


def inspect_checkpoint(database, opening_cash, checkpoint, key):
    """Inspect one verified journal snapshot using the existing read-only facade.

    A matching HMAC establishes agreement with the supplied key only. The local
    mode marker is not authenticated enrollment. Pending publication is rejected
    by the existing checkpoint verifier, with no repair or report of success.
    """
    database, checkpoint = _input_path(database), _input_path(checkpoint)
    if database.samefile(checkpoint):
        raise ValueError("Database and checkpoint must be separate files")
    if type(key) is not bytes or not 32 <= len(key) <= 4096:
        raise ValueError("Checkpoint key must contain 32..4096 raw bytes")
    with localcontext(Context(prec=50)):
        ledger = DurableLedger(database, opening_cash=opening_cash,
                               checkpoint_path=checkpoint, checkpoint_key=key)
        try:
            # The facade's initial verification has ended its transaction. Recheck
            # the tip and metadata together in a new stable read snapshot.
            ledger.db.execute("BEGIN")
            validate_ledger_schema(ledger.db)
            amount = ledger.db.execute(
                "SELECT value FROM ledger_meta WHERE key='opening_cash'"
            ).fetchone()
            if amount is None or exact_cash(amount[0]) != ledger.opening_cash:
                raise ValueError("Opening cash changed during inspection")
            ledger.balances()  # Replays balances and checks the facade's pinned tip.
            sequence, digest = verify_checkpoint(
                ledger.db, ledger.opening_cash, checkpoint, key
            )
            identity = read_ledger_identity(ledger.db)
            row = ledger.db.execute(
                "SELECT value FROM ledger_meta WHERE key='checkpoint_writer_mode'"
            ).fetchone()
            mode = None if row is None else row[0]
            if mode is None:
                boundary = "LEGACY_DIRECT_WRITE_BOUNDARY_NOT_ESTABLISHED"
            elif mode == "managed-v1":
                boundary = "LOCAL_MANAGED_MARKER_PRESENT"
            else:
                boundary = "UNKNOWN_MODE_DIRECT_WRITES_FAIL_CLOSED"
            return {
                "version": "ARIYAN-A020-CHECKPOINT-DIAGNOSTIC-V1",
                "inspection": "READ_ONLY_NO_ENROLLMENT_OR_REPAIR",
                "checkpoint_matches_supplied_key_and_journal": True,
                "sequence": sequence, "journal_digest": digest,
                "ledger_identity_label": identity,
                "local_writer_mode": mode, "boundary": boundary,
                "publication_pending": False,
                "key_authority_established": False,
                "writer_enrollment_authenticated": False,
                "mode_marker_authenticated": False,
                "ledger_identity_authenticated_by_checkpoint": False,
                "independent_rollback_resistance_established": False,
                "write_authorized": False, "live_authorized": False,
                "limitations": [
                    "External checkpoint publication does not enroll a ledger as managed.",
                    "The local mode marker describes the ordinary DurableLedger API guard only.",
                    "A mode marker can change without changing the anchored journal tip.",
                    "A matching older ledger and checkpoint can still pass this comparison.",
                    "The supplied key's independent authority and custody are not assessed.",
                    "This observation is a snapshot, not a continuing guarantee or write admission.",
                ],
            }
        finally:
            try:
                if ledger.db.in_transaction:
                    ledger.db.execute("ROLLBACK")
            finally:
                ledger.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--opening-cash", required=True)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--checkpoint-key-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        key_path = _input_path(args.checkpoint_key_file)
        if any(key_path.samefile(_input_path(path)) for path in
               (args.database, args.checkpoint)):
            raise ValueError("Key file must be separate from database and checkpoint")
        with key_path.open("rb") as stream:
            key = stream.read(4097)
        report = inspect_checkpoint(args.database, args.opening_cash, args.checkpoint, key)
    except (OSError, ValueError, TypeError, ArithmeticError, sqlite3.Error):
        # Do not echo exceptions: malformed private inputs can contain key material.
        parser.exit(2, "Checkpoint diagnostic rejected; no enrollment or repair performed.\n")
    print(json.dumps(report, sort_keys=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    main()
