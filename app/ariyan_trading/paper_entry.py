"""A028 Predictability Gate boundary for explicit offline paper orders."""

from .checkpoint_coordinator import execute_checkpointed_trade
from .predictability_gate import assess_new_exposure


class PaperEntryDenied(RuntimeError):
    """The Predictability Gate blocked a new paper entry."""

    def __init__(self, assessment):
        self.assessment = assessment
        super().__init__('Paper BUY blocked by Predictability Gate')


def execute_governed_paper_trade(
    ledger, action, request_id, quantity, price, *, anchor_path, key,
    review_directory=None,
):
    """Block BUY before accessing the ledger and delegate SELL to A006."""
    if action == 'BUY':
        # A027 has no positive admission path. Even an unexpected assessment
        # cannot authorize a BUY through this version of the boundary.
        raise PaperEntryDenied(assess_new_exposure(review_directory))
    if action != 'SELL':
        raise ValueError('Only explicit BUY or SELL is supported')
    return execute_checkpointed_trade(
        ledger, action, request_id, quantity, price,
        anchor_path=anchor_path, key=key,
    )
