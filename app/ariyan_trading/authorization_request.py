"""A006 P3C12-B6C1: structural authorization request binding.

No independent authentication, trusted clock, freshness proof,
rollback resistance, ledger mutation, or trading permission.
"""

from dataclasses import dataclass

from ariyan_trading.authorization_validation import (
    valid_uuid,
    valid_name,
    OPERATIONS,
    validate_authorization_evidence,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationDecision,
    WriterAuthorizationStatus,
)


@dataclass(frozen=True)
class AuthorizationRequest:
    ledger_id: str
    writer_id: str
    operation: str
    request_time: int


def validate_authorization_request(request):
    if type(request) is not AuthorizationRequest:
        return False

    return (
        valid_uuid(request.ledger_id)
        and valid_name(request.writer_id)
        and type(request.operation) is str
        and request.operation in OPERATIONS
        and type(request.request_time) is int
        and request.request_time >= 0
    )


def assess_request_binding(*, evidence, request):
    """Compare caller-supplied structures; never grant permission."""

    def deny(reason):
        return WriterAuthorizationDecision(
            WriterAuthorizationStatus.DENY,
            reason,
        )

    if not validate_authorization_evidence(evidence):
        return deny("Invalid authorization evidence")

    if not validate_authorization_request(request):
        return deny("Invalid authorization request")

    if evidence.ledger_id != request.ledger_id:
        return deny("Ledger identity mismatch")

    if evidence.writer_id != request.writer_id:
        return deny("Writer identity mismatch")

    if request.operation not in evidence.allowed_operations:
        return deny("Operation not permitted")

    if not (
        evidence.valid_from
        <= request.request_time
        < evidence.valid_until
    ):
        return deny("Request outside authorization interval")

    return WriterAuthorizationDecision(
        WriterAuthorizationStatus.UNCERTAIN,
        "Independent authorization trust not established",
    )
