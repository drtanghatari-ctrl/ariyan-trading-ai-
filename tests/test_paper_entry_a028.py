"""Offline paper boundary integration and preservation of coordinator behavior."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ariyan_trading import paper_entry
from ariyan_trading.checkpoint_coordinator import (
    PENDING, PublicationUncertain, execute_checkpointed_trade,
)
from ariyan_trading.checkpoint_publication import PublicationState
from ariyan_trading.durable_ledger import DurableLedger
from ariyan_trading.journal_store import verify_protected_journal
from ariyan_trading.trust_anchor import create_anchor, write_anchor


class PaperEntryA028Tests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.anchor = self.root / 'anchor.json'
        self.key = b'A028-disposable-test-key-only-32B!'
        self.ledger = DurableLedger(self.root / 'ledger.sqlite', opening_cash='1000.00')
        self.addCleanup(self.ledger.close)
        with self.ledger.db:
            self.ledger.db.execute('BEGIN')
            digest = verify_protected_journal(self.ledger.db, self.ledger.opening_cash)
        write_anchor(self.anchor, create_anchor(0, digest, self.key), self.key)

    def execute(self, action, request_id='order-1', **kwargs):
        return paper_entry.execute_governed_paper_trade(
            self.ledger, action, request_id, '1', '10.00',
            anchor_path=self.anchor, key=self.key, **kwargs,
        )

    def snapshot(self):
        return (
            self.ledger.balances(),
            tuple(self.ledger.db.iterdump()),
            self.anchor.read_bytes(),
        )

    def seed_position(self):
        execute_checkpointed_trade(
            self.ledger, 'BUY', 'seed-buy', '2', '10.00',
            anchor_path=self.anchor, key=self.key,
        )

    def test_denied_buys_leave_all_state_unchanged(self):
        before = self.snapshot()
        for directory, reason in (
            (None, 'MISSING_VALIDATION_EVIDENCE'),
            (self.root / 'missing', 'UNVERIFIABLE_REVIEW_EVIDENCE'),
        ):
            with self.subTest(reason=reason):
                statements = []
                self.ledger.db.set_trace_callback(statements.append)
                try:
                    with patch.object(paper_entry, 'execute_checkpointed_trade') as writer:
                        with self.assertRaises(paper_entry.PaperEntryDenied) as caught:
                            self.execute('BUY', review_directory=directory)
                        writer.assert_not_called()
                finally:
                    self.ledger.db.set_trace_callback(None)
                self.assertEqual(statements, [])
                self.assertEqual(caught.exception.assessment['decision'], 'NO_TRADE')
                self.assertEqual(caught.exception.assessment['reason'], reason)
                self.assertEqual(self.snapshot(), before)

    def test_unexpected_positive_assessment_cannot_admit_a_buy(self):
        before = self.snapshot()
        with patch.object(paper_entry, 'assess_new_exposure', return_value={'decision': 'ALLOW'}):
            with self.assertRaises(paper_entry.PaperEntryDenied):
                self.execute('BUY')
        self.assertEqual(self.snapshot(), before)

    def test_invalid_action_does_not_use_either_path(self):
        with patch.object(paper_entry, 'assess_new_exposure') as gate:
            with patch.object(paper_entry, 'execute_checkpointed_trade') as writer:
                with self.assertRaisesRegex(ValueError, 'Only explicit BUY or SELL'):
                    self.execute('HOLD')
                gate.assert_not_called()
                writer.assert_not_called()

    def test_sell_keeps_checkpoint_and_duplicate_request_controls(self):
        self.seed_position()
        with patch.object(paper_entry, 'assess_new_exposure') as gate:
            result = self.execute('SELL', review_directory=self.root / 'missing')
            gate.assert_not_called()
        self.assertIs(result['state'], PublicationState.DURABLE)
        self.assertEqual(result['sequence'], 2)
        self.assertEqual(result['units'], 1)
        before = self.snapshot()
        with self.assertRaises(sqlite3.IntegrityError):
            self.execute('SELL')
        self.assertEqual(self.snapshot(), before)

    def test_uncertain_sell_is_propagated_and_never_retried(self):
        self.seed_position()
        anchor_before = self.anchor.read_bytes()
        with patch('ariyan_trading.checkpoint_coordinator.write_anchor',
                   side_effect=OSError('simulated publication failure')) as publish:
            with self.assertRaises(PublicationUncertain):
                self.execute('SELL')
            publish.assert_called_once()
        self.assertEqual(self.anchor.read_bytes(), anchor_before)
        self.assertEqual(self.ledger.balances()[1], 1)
        pending = self.ledger.db.execute(
            'SELECT value FROM ledger_meta WHERE key=?', (PENDING,),
        ).fetchone()
        self.assertIsNotNone(pending)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'pending or uncertain'):
            self.execute('SELL', request_id='another-order')
        self.assertEqual(self.snapshot(), before)
