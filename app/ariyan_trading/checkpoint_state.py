"""A006 fail-closed checkpoint evidence classification.

Pure decision logic only. No file I/O, database writes,
anchor publication, recovery, or trading authorization.
"""

from dataclasses import dataclass
from enum import Enum


class CheckpointState(str, Enum):
    VERIFIED = "VERIFIED"
    MISSING = "MISSING"
    INVALID = "INVALID"
    STALE = "STALE"
    DIVERGENT = "DIVERGENT"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class CheckpointDecision:
    state: CheckpointState
    verification_eligible: bool
    reason: str


def classify_checkpoint(
    *,
    journal_sequence,
    journal_digest,
    anchor_sequence=None,
    anchor_digest=None,
    anchor_authenticated=False,
    publication_uncertain=False,
):
    """Classify supplied evidence without changing it.

    This is not a substitute for authenticated verification.
    The caller must establish a consistent journal snapshot.
    """
    def decision(state, reason):
        return CheckpointDecision(
            state=state,
            verification_eligible=(state is CheckpointState.VERIFIED),
            reason=reason,
        )

    if (
        type(anchor_authenticated) is not bool
        or type(publication_uncertain) is not bool
    ):
        return decision(
            CheckpointState.INVALID,
            "Checkpoint control flags must be Boolean",
        )

    if publication_uncertain:
        return decision(
            CheckpointState.UNCERTAIN,
            "Checkpoint publication outcome is uncertain",
        )

    if anchor_sequence is None or anchor_digest is None:
        return decision(
            CheckpointState.MISSING,
            "Authenticated checkpoint evidence is missing",
        )

    if not anchor_authenticated:
        return decision(
            CheckpointState.INVALID,
            "Checkpoint authentication has not been established",
        )

    if (
        type(journal_sequence) is not int
        or journal_sequence < 0
        or type(anchor_sequence) is not int
        or anchor_sequence < 0
        or not isinstance(journal_digest, str)
        or not isinstance(anchor_digest, str)
        or len(journal_digest) != 64
        or len(anchor_digest) != 64
    ):
        return decision(
            CheckpointState.INVALID,
            "Checkpoint evidence has invalid structure",
        )

    try:
        bytes.fromhex(journal_digest)
        bytes.fromhex(anchor_digest)
    except ValueError:
        return decision(
            CheckpointState.INVALID,
            "Checkpoint digest encoding is invalid",
        )

    if anchor_sequence < journal_sequence:
        return decision(
            CheckpointState.STALE,
            "Authenticated anchor precedes journal tip",
        )

    if anchor_sequence != journal_sequence:
        return decision(
            CheckpointState.DIVERGENT,
            "Anchor and journal sequences differ",
        )

    if anchor_digest.lower() != journal_digest.lower():
        return decision(
            CheckpointState.DIVERGENT,
            "Anchor and journal digests differ",
        )

    return decision(
        CheckpointState.VERIFIED,
        "Authenticated checkpoint matches supplied journal evidence",
    )
