"""Governed boundary for explicit offline paper orders."""

from .checkpoint_coordinator import execute_checkpointed_trade
from .predictability_gate import assess_new_exposure


PAPER_EXECUTION_STATES = ("NORMAL", "STOP", "FREEZE")


class PaperEntryDenied(RuntimeError):
    """The Predictability Gate blocked a new paper entry."""

    def __init__(self, assessment):
        self.assessment = assessment
        super().__init__('Paper BUY blocked by Predictability Gate')


class PaperExecutionDenied(RuntimeError):
    """An explicit paper execution state blocked the order."""

    def __init__(self, action, execution_state):
        self.action = action
        self.execution_state = execution_state
        super().__init__(f"Paper {action} blocked by {execution_state}")


def execute_governed_paper_trade(
    ledger, action, request_id, quantity, price, *, anchor_path, key,
    review_directory=None, execution_state="NORMAL",
):
    """Apply the caller's paper state before any gate or ledger access."""
    if action not in ("BUY", "SELL"):
        raise ValueError("Only explicit BUY or SELL is supported")
    if type(execution_state) is not str or execution_state not in PAPER_EXECUTION_STATES:
        raise ValueError("Unsupported paper execution state")
    if execution_state == "FREEZE" or (execution_state == "STOP" and action == "BUY"):
        raise PaperExecutionDenied(action, execution_state)
    if action == 'BUY':
        # A027 has no positive admission path. Even an unexpected assessment
        # cannot authorize a BUY through this version of the boundary.
        raise PaperEntryDenied(assess_new_exposure(review_directory))
    return execute_checkpointed_trade(
        ledger, action, request_id, quantity, price,
        anchor_path=anchor_path, key=key,
    )
