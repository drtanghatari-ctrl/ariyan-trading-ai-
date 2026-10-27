"""A006-WB02-P3C pure enrollment state machine.

DESIGN MODEL ONLY.

No database I/O, filesystem publication, recovery authorization,
or trading permissions are implemented here.

Events describe externally verified outcomes. This module does
not verify that those outcomes actually occurred.
"""

from dataclasses import dataclass
from enum import Enum


class EnrollmentState(str, Enum):
    LEGACY = "legacy"
    PREPARING = "preparing"
    MANAGED = "managed"
    UNCERTAIN = "uncertain"
    INVALID = "invalid"


class EnrollmentEvent(str, Enum):
    PREPARATION_COMMITTED = "preparation_committed"
    PUBLICATION_VERIFIED = "publication_verified"
    OUTCOME_UNCERTAIN = "outcome_uncertain"
    EVIDENCE_INVALID = "evidence_invalid"


@dataclass(frozen=True)
class EnrollmentDecision:
    state: EnrollmentState
    direct_writes_allowed: bool
    enrollment_complete: bool


def _decision(state):
    return EnrollmentDecision(
        state=state,
        direct_writes_allowed=(state is EnrollmentState.LEGACY),
        enrollment_complete=(state is EnrollmentState.MANAGED),
    )


_TRANSITIONS = {
    (EnrollmentState.LEGACY,
     EnrollmentEvent.PREPARATION_COMMITTED):
        EnrollmentState.PREPARING,

    (EnrollmentState.PREPARING,
     EnrollmentEvent.PUBLICATION_VERIFIED):
        EnrollmentState.MANAGED,
}


def transition_enrollment(state, event):
    """Return a decision for an explicitly reported event.

    Invalid transitions fail closed by raising ValueError.
    The caller must authenticate and verify external evidence.
    """
    if not isinstance(state, EnrollmentState):
        raise TypeError("Invalid enrollment state")

    if not isinstance(event, EnrollmentEvent):
        raise TypeError("Invalid enrollment event")

    if event is EnrollmentEvent.EVIDENCE_INVALID:
        return _decision(EnrollmentState.INVALID)

    if event is EnrollmentEvent.OUTCOME_UNCERTAIN:
        if state is EnrollmentState.INVALID:
            return _decision(EnrollmentState.INVALID)
        return _decision(EnrollmentState.UNCERTAIN)

    next_state = _TRANSITIONS.get((state, event))

    if next_state is None:
        raise ValueError(
            "Enrollment transition prohibited: "
            f"{state.value} + {event.value}"
        )

    return _decision(next_state)


def classify_enrollment_state(state):
    """Classify a supplied state without performing transitions."""
    if not isinstance(state, EnrollmentState):
        raise TypeError("Invalid enrollment state")

    return _decision(state)
