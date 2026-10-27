"""Independent SQLite-backed Decimal ledger foundation."""

import sqlite3
from pathlib import Path

from .checkpoint_verifier import verify_checkpoint
from .ledger_validation import exact_cash
from .initialization_lock import initialization_lock
from .schema_validation import validate_ledger_schema
from .journal_store import (
    append_journal_commitment,
    create_protected_journal,
    protection_status,
    verify_protected_journal,
)


class DurableLedger:
    def __init__(self, path, opening_cash=None, *, checkpoint_path=None, checkpoint_key=None):
        if (checkpoint_path is None) != (checkpoint_key is None):
            raise ValueError('Checkpoint path and key must be supplied together')
        self.path = Path(path)

        if not self.path.parent.is_dir():
            raise FileNotFoundError(
                "Ledger directory does not exist"
            )

        self.checkpoint_read_only = checkpoint_path is not None
        if self.checkpoint_read_only:
            self._initialize_verified_read_only(
                opening_cash, checkpoint_path, checkpoint_key
            )
        else:
            with initialization_lock(self.path):
                self._initialize(opening_cash)

    def _initialize_verified_read_only(
        self, opening_cash, checkpoint_path, checkpoint_key
    ):
        """Verify an existing ledger using a read-only SQLite connection."""
        if not self.path.is_file():
            raise ValueError("Cannot open a new ledger with a checkpoint")

        uri = self.path.resolve().as_uri() + "?mode=ro"
        self.db = sqlite3.connect(
            uri, uri=True, isolation_level=None, timeout=10
        )

        try:
            self.db.execute("BEGIN")

            # Establish a stable SQLite read snapshot.
            self.db.execute(
                "SELECT name FROM sqlite_master LIMIT 1"
            ).fetchall()

            integrity = self.db.execute(
                "PRAGMA integrity_check"
            ).fetchall()
            if integrity != [("ok",)]:
                raise ValueError(
                    "SQLite database integrity check failed"
                )

            validate_ledger_schema(self.db)

            row = self.db.execute(
                "SELECT value FROM ledger_meta "
                "WHERE key='opening_cash'"
            ).fetchone()
            if row is None:
                raise ValueError("Existing ledger missing opening cash")

            amount = exact_cash(row[0])
            if opening_cash is not None:
                if exact_cash(opening_cash) != amount:
                    raise ValueError("Opening cash mismatch")

            self.opening_cash = amount
            self.journal_protection = protection_status(self.db)

            if self.journal_protection != "protected":
                raise ValueError(
                    "Unprotected journal cannot be anchored"
                )

            self.balances()
            self._verified_checkpoint = verify_checkpoint(
                self.db, amount, checkpoint_path, checkpoint_key
            )
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def _initialize(self, opening_cash, checkpoint_path=None, checkpoint_key=None):
        new_database = not self.path.exists()

        self.db = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=10,
        )

        try:
            if not new_database:
                integrity = self.db.execute(
                    "PRAGMA integrity_check"
                ).fetchall()

                if integrity != [("ok",)]:
                    raise ValueError(
                        "SQLite database integrity check failed"
                    )

            self.db.execute("BEGIN IMMEDIATE")

            if new_database:
                existing_opening = self.db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='ledger_meta'"
                ).fetchone()

                if existing_opening is not None:
                    existing_journal = self.db.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' "
                        "AND name='ledger_entries'"
                    ).fetchone()

                    if existing_journal is None:
                        raise ValueError(
                            "Incomplete concurrent initialization"
                        )

                    row = self.db.execute(
                        "SELECT value FROM ledger_meta "
                        "WHERE key='opening_cash'"
                    ).fetchone()

                    if row is None:
                        raise ValueError(
                            "Incomplete concurrent initialization"
                        )

                    new_database = False

            self.db.execute(
                "CREATE TABLE IF NOT EXISTS ledger_meta ("
                "key TEXT PRIMARY KEY, "
                "value TEXT NOT NULL)"
            )

            if new_database:
                self.db.execute(
                    "CREATE TABLE ledger_entries ("
                    "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "request_id TEXT NOT NULL UNIQUE, "
                    "action TEXT NOT NULL "
                    "CHECK(action IN ('BUY','SELL')), "
                    "quantity TEXT NOT NULL, "
                    "price TEXT NOT NULL, "
                    "cash_delta TEXT NOT NULL, "
                    "units_delta TEXT NOT NULL)"
                )
            else:
                journal = self.db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' "
                    "AND name='ledger_entries'"
                ).fetchone()

                if journal is None:
                    raise ValueError(
                        "Existing ledger missing transaction journal"
                    )

            row = self.db.execute(
                "SELECT value FROM ledger_meta "
                "WHERE key='opening_cash'"
            ).fetchone()

            if row is None:
                if not new_database:
                    raise ValueError(
                        "Existing ledger missing opening cash"
                    )
                if opening_cash is None:
                    raise ValueError(
                        "Opening cash required for new ledger"
                    )

                amount = exact_cash(opening_cash)

                self.db.execute(
                    "INSERT INTO ledger_meta(key,value) "
                    "VALUES ('opening_cash',?)",
                    (str(amount),),
                )
            else:
                amount = exact_cash(row[0])

                if opening_cash is not None:
                    requested = exact_cash(opening_cash)
                    if requested != amount:
                        raise ValueError(
                            "Opening cash mismatch"
                        )

            validate_ledger_schema(self.db)
            if new_database:
                create_protected_journal(self.db, amount)
            self.opening_cash = amount
            self.journal_protection = protection_status(self.db)
            if self.journal_protection == "protected":
                verify_protected_journal(self.db, amount)
            self.balances()
            if checkpoint_path is not None:
                if new_database:
                    raise ValueError('Cannot open a new ledger with a checkpoint')
                verify_checkpoint(
                    self.db, amount, checkpoint_path, checkpoint_key
                )
            self.db.execute("COMMIT")

        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            self.db.close()
            raise

    def balances(self):
        """Validate and replay the persistent journal."""
        if not self.db.in_transaction:
            self.db.execute('BEGIN')
            try:
                result = self._replay_balances()
                self.db.execute('COMMIT')
                return result
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute('ROLLBACK')
                raise
        return self._replay_balances()

    def _replay_balances(self):
        if self.journal_protection == 'protected':
            digest = verify_protected_journal(
                self.db, self.opening_cash
            )
            checkpoint = getattr(self, "_verified_checkpoint", None)
            if self.checkpoint_read_only and checkpoint is not None:
                sequence = self.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0]
                expected_sequence, expected_digest = checkpoint
                if sequence != expected_sequence:
                    raise ValueError("Checkpoint sequence mismatch")
                if digest != expected_digest:
                    raise ValueError("Checkpoint digest mismatch")
        from decimal import Decimal, localcontext

        from .ledger_validation import (
            exact_cash,
            validated_trade,
        )

        with localcontext() as ctx:
            ctx.prec = 50
            cash = self.opening_cash
            units = Decimal("0")

            rows = self.db.execute(
                "SELECT sequence,action,quantity,price,"
                "cash_delta,units_delta "
                "FROM ledger_entries ORDER BY sequence"
            )

            expected_sequence = 1

            for (
                sequence, action, quantity, price,
                cash_delta, units_delta,
            ) in rows:
                if sequence != expected_sequence:
                    raise ValueError("Journal sequence gap")

                if action not in ("BUY", "SELL"):
                    raise ValueError("Unsupported journal action")

                qty, _, cost = validated_trade(
                    quantity, price
                )

                if action == "BUY":
                    if Decimal(units_delta) != qty:
                        raise ValueError("Invalid BUY units delta")
                    if Decimal(cash_delta) != -cost:
                        raise ValueError("Invalid BUY cash delta")
                    if cost > cash:
                        raise ValueError("Journal overspent cash")
                    cash -= cost
                    units += qty
                else:
                    if Decimal(units_delta) != -qty:
                        raise ValueError("Invalid SELL units delta")
                    if Decimal(cash_delta) != cost:
                        raise ValueError("Invalid SELL cash delta")
                    if qty > units:
                        raise ValueError("Journal oversold units")
                    cash += cost
                    units -= qty
                expected_sequence += 1

        return cash, units

    def _require_direct_writer_permission(self):
        """Reject direct trades on checkpoint-managed ledgers."""
        row = self.db.execute(
            "SELECT value FROM ledger_meta WHERE key=?",
            ("checkpoint_writer_mode",),
        ).fetchone()

        if row is None:
            return

        if row[0] == "managed-v1":
            raise RuntimeError(
                "Checkpoint-managed ledger requires coordinator"
            )

        raise RuntimeError(
            "Unknown checkpoint writer mode; direct writes prohibited"
        )

    def record_buy(self, request_id, quantity, price):
        """Atomically record a validated paper BUY."""
        from decimal import localcontext

        from .ledger_validation import validated_trade

        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A nonempty request ID is required")

        quantity, price, cost = validated_trade(quantity, price)

        if self.checkpoint_read_only:
            raise RuntimeError(
                "Checkpoint-verified ledger is read-only"
            )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._require_direct_writer_permission()
            existing = self.db.execute(
                "SELECT 1 FROM ledger_entries "
                "WHERE request_id=?",
                (request_id,),
            ).fetchone()

            if existing is not None:
                raise ValueError("Duplicate request ID")

            cash, units = self.balances()

            if cost > cash:
                raise ValueError("Insufficient cash")

            with localcontext() as ctx:
                ctx.prec = 50
                cash_delta = -cost

            self.db.execute(
                "INSERT INTO ledger_entries "
                "(request_id,action,quantity,price,"
                "cash_delta,units_delta) "
                "VALUES (?,?,?,?,?,?)",
                (
                    request_id,
                    "BUY",
                    str(quantity),
                    str(price),
                    str(cash_delta),
                    str(quantity),
                ),
            )

            if self.journal_protection == 'protected':
                append_journal_commitment(
                    self.db, self.opening_cash
                )
            self.db.execute("COMMIT")
            return self.balances()

        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def record_sell(self, request_id, quantity, price):
        """Atomically record a validated paper SELL."""
        from decimal import localcontext

        from .ledger_validation import validated_trade

        if not isinstance(request_id, str) or not request_id.strip():
            raise ValueError("A nonempty request ID is required")

        quantity, price, proceeds = validated_trade(
            quantity, price
        )

        if self.checkpoint_read_only:
            raise RuntimeError(
                "Checkpoint-verified ledger is read-only"
            )
        self.db.execute("BEGIN IMMEDIATE")
        try:
            self._require_direct_writer_permission()
            existing = self.db.execute(
                "SELECT 1 FROM ledger_entries "
                "WHERE request_id=?",
                (request_id,),
            ).fetchone()

            if existing is not None:
                raise ValueError("Duplicate request ID")

            cash, units = self.balances()

            if quantity > units:
                raise ValueError("Insufficient units")

            with localcontext() as ctx:
                ctx.prec = 50
                units_delta = -quantity

            self.db.execute(
                "INSERT INTO ledger_entries "
                "(request_id,action,quantity,price,"
                "cash_delta,units_delta) "
                "VALUES (?,?,?,?,?,?)",
                (
                    request_id,
                    "SELL",
                    str(quantity),
                    str(price),
                    str(proceeds),
                    str(units_delta),
                ),
            )

            if self.journal_protection == 'protected':
                append_journal_commitment(
                    self.db, self.opening_cash
                )
            self.db.execute("COMMIT")
            return self.balances()

        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()
