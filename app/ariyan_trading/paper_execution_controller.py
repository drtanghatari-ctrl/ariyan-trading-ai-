"""Serialize governed paper orders and signed escalations in one controller."""

import time
from contextlib import nullcontext
from pathlib import Path
from threading import Lock

from .initialization_lock import initialization_lock
from .paper_active_selection import _replace_active_selection, read_paper_active_selection
from .paper_entry import execute_governed_paper_trade
from .paper_execution_state import read_paper_execution_state
from .paper_state_escalation import prepare_paper_escalation


class PaperExecutionController:
    """Use a pinned paper state and serialize participating requests."""

    def __init__(self, state_path, *, ledger_identity, expected_state_sha256,
                 checkpoint_key, operator_public_key):
        if expected_state_sha256 is None:
            raise ValueError("An independently retained paper state pin is required")
        if type(operator_public_key) is not bytes or len(operator_public_key) != 32:
            raise ValueError("Expected an independently supplied raw Ed25519 public key")
        path = Path(state_path).absolute()
        read_paper_execution_state(
            path, ledger_identity, key=checkpoint_key, expected_sha256=expected_state_sha256,
        )
        self._active = (path, expected_state_sha256)
        self._ledger_identity = ledger_identity
        self._checkpoint_key = checkpoint_key
        self._operator_public_key = operator_public_key
        self._lock = Lock()
        self._selector = None

    @classmethod
    def reopen(cls, selector_path, *, ledger_identity, expected_state_sha256,
               checkpoint_key, operator_public_key):
        """Reopen only when the stored selection matches the separately retained pin."""
        selector = Path(selector_path).resolve()
        with initialization_lock(selector):
            state_path, pin = read_paper_active_selection(
                selector, ledger_identity, key=checkpoint_key,
            )
            if type(expected_state_sha256) is not str or pin != expected_state_sha256:
                raise ValueError("Active selection differs from the independently retained pin")
            controller = cls(
                state_path, ledger_identity=ledger_identity, expected_state_sha256=pin,
                checkpoint_key=checkpoint_key, operator_public_key=operator_public_key,
            )
        controller._selector = selector
        return controller

    def _selector_lock(self):
        if self._selector is None:
            return nullcontext()
        return initialization_lock(self._selector)

    def _current_selection(self):
        if self._selector is not None and read_paper_active_selection(
            self._selector, self._ledger_identity, key=self._checkpoint_key,
        ) != self._active:
            raise ValueError("Active selection changed outside this paper controller")
        return self._active

    def execute(self, ledger, action, request_id, quantity, price, *,
                anchor_path, review_directory=None):
        """Submit against the active pin and hold the lock through completion."""
        with self._lock, self._selector_lock():
            if getattr(ledger, "ledger_identity", None) != self._ledger_identity:
                raise ValueError("Paper controller ledger identity mismatch")
            path, pin = self._current_selection()
            return execute_governed_paper_trade(
                ledger, action, request_id, quantity, price,
                anchor_path=anchor_path, key=self._checkpoint_key,
                review_directory=review_directory, execution_state_path=path,
                expected_execution_state_sha256=pin,
            )

    def activate_escalation(self, next_path, intent, signature):
        """Prepare and select a successor, returning its pin for the caller."""
        with self._lock, self._selector_lock():
            path, pin = self._current_selection()
            successor = Path(next_path).absolute()
            next_pin = prepare_paper_escalation(
                path, successor, intent, signature, ledger_identity=self._ledger_identity,
                expected_current_sha256=pin, checkpoint_key=self._checkpoint_key,
                operator_public_key=self._operator_public_key,
                as_of_ms=time.time_ns() // 1_000_000,
            )
            if self._selector is not None:
                _replace_active_selection(
                    self._selector, successor, next_pin,
                    self._ledger_identity, self._checkpoint_key,
                )
            self._active = (successor, next_pin)
            return next_pin
