"""A006 coordinator concurrency with deterministic synchronization."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from threading import Event
from unittest.mock import patch

from ariyan_trading import checkpoint_coordinator as coordinator
from ariyan_trading.checkpoint_publication import (
    PublicationEvent, PublicationState,
)
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor

KEY = b"A006-concurrency-test-key-only!!!"


class CoordinatorConcurrencyA006Tests(unittest.TestCase):
    def prepare(self, root, mode):
        database = root / "ledger.sqlite"
        anchor = root / "anchor.json"
        ledger = DurableLedger(database, opening_cash="1000.00")
        try:
            actual = ledger.db.execute(
                "PRAGMA journal_mode=" + mode
            ).fetchone()[0]
            self.assertEqual(actual.upper(), mode)
            ledger.db.execute("BEGIN")
            digest = verify_protected_journal(
                ledger.db, ledger.opening_cash
            )
            ledger.db.commit()
            write_anchor(
                anchor, create_anchor(0, digest, KEY), KEY
            )
        finally:
            ledger.close()
        return database, anchor

    def trade(self, ledger, anchor, request):
        return coordinator.execute_checkpointed_trade(
            ledger, "BUY", request, "1", "10.00",
            anchor_path=anchor, key=KEY,
        )

    def verify_final(self, database, anchor, cash, sequence):
        reader = DurableLedger(
            database, checkpoint_path=anchor, checkpoint_key=KEY
        )
        try:
            self.assertEqual(reader.balances()[0], Decimal(cash))
            self.assertEqual(
                reader.db.execute(
                    "SELECT COUNT(*) FROM ledger_entries"
                ).fetchone()[0],
                sequence,
            )
        finally:
            reader.close()

    def test_competitor_cannot_enter_commit_publication_gap(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as directory:
                    database, anchor = self.prepare(Path(directory), mode)
                    committed = Event()
                    release = Event()
                    real_advance = coordinator.advance_publication

                    def pause_after_commit(state, event):
                        if event is PublicationEvent.COMMIT_CONFIRMED:
                            committed.set()
                            if not release.wait(10):
                                raise RuntimeError("Test release timed out")
                        return real_advance(state, event)

                    def first_writer():
                        ledger = DurableLedger(database)
                        try:
                            return self.trade(ledger, anchor, "first")
                        finally:
                            ledger.close()

                    with patch.object(
                        coordinator, "advance_publication",
                        side_effect=pause_after_commit,
                    ):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(first_writer)
                            try:
                                self.assertTrue(
                                    committed.wait(10),
                                    "First trade did not reach commit boundary",
                                )
                                competitor = DurableLedger(database)
                                try:
                                    before = anchor.read_bytes()
                                    with self.assertRaisesRegex(
                                        ValueError, "pending or uncertain"
                                    ):
                                        self.trade(
                                            competitor, anchor, "competitor"
                                        )
                                    self.assertEqual(anchor.read_bytes(), before)
                                    self.assertEqual(
                                        competitor.balances()[0],
                                        Decimal("990.00"),
                                    )
                                finally:
                                    competitor.close()
                            finally:
                                release.set()
                            result = future.result(timeout=15)
                    self.assertIs(
                        result["state"], PublicationState.DURABLE
                    )
                    self.verify_final(database, anchor, "990.00", 1)

    def test_separate_connections_can_publish_successive_trades(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as directory:
                    database, anchor = self.prepare(Path(directory), mode)
                    first = DurableLedger(database)
                    second = DurableLedger(database)
                    try:
                        self.trade(first, anchor, "first")
                        result = self.trade(second, anchor, "second")
                        self.assertEqual(result["sequence"], 2)
                    finally:
                        second.close()
                        first.close()
                    self.verify_final(database, anchor, "980.00", 2)

    def test_duplicate_from_another_connection_cannot_reexecute(self):
        for mode in ("DELETE", "WAL"):
            with self.subTest(mode=mode):
                with tempfile.TemporaryDirectory() as directory:
                    database, anchor = self.prepare(Path(directory), mode)
                    first = DurableLedger(database)
                    second = DurableLedger(database)
                    try:
                        self.trade(first, anchor, "same-request")
                        before = anchor.read_bytes()
                        with self.assertRaises(sqlite3.IntegrityError):
                            self.trade(second, anchor, "same-request")
                        self.assertEqual(anchor.read_bytes(), before)
                    finally:
                        second.close()
                        first.close()
                    self.verify_final(database, anchor, "990.00", 1)


if __name__ == "__main__":
    unittest.main()
