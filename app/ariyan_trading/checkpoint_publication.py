"""A006 publication ordering model.

Pure transition logic. Does not perform I/O, authenticate evidence,
authorize recovery, or authorize trading. Events must come from a
future coordinator observing actual transaction and filesystem outcomes.
"""

from enum import Enum


class PublicationState(str, Enum):
    READY = "READY"
    COMMITTED = "COMMITTED"
    PUBLISHING = "PUBLISHING"
    DURABLE = "DURABLE"
    CANCELLED = "CANCELLED"
    UNCERTAIN = "UNCERTAIN"


class PublicationEvent(str, Enum):
    COMMIT_CONFIRMED = "COMMIT_CONFIRMED"
    ABORT_CONFIRMED = "ABORT_CONFIRMED"
    PUBLICATION_STARTED = "PUBLICATION_STARTED"
    PUBLICATION_DURABLE = "PUBLICATION_DURABLE"
    OUTCOME_UNCERTAIN = "OUTCOME_UNCERTAIN"


_TRANSITIONS = {
    (PublicationState.READY, PublicationEvent.COMMIT_CONFIRMED):
        PublicationState.COMMITTED,
    (PublicationState.READY, PublicationEvent.ABORT_CONFIRMED):
        PublicationState.CANCELLED,
    (PublicationState.READY, PublicationEvent.OUTCOME_UNCERTAIN):
        PublicationState.UNCERTAIN,
    (PublicationState.COMMITTED, PublicationEvent.PUBLICATION_STARTED):
        PublicationState.PUBLISHING,
    (PublicationState.COMMITTED, PublicationEvent.OUTCOME_UNCERTAIN):
        PublicationState.UNCERTAIN,
    (PublicationState.PUBLISHING, PublicationEvent.PUBLICATION_DURABLE):
        PublicationState.DURABLE,
    (PublicationState.PUBLISHING, PublicationEvent.OUTCOME_UNCERTAIN):
        PublicationState.UNCERTAIN,
}


def advance_publication(state, event):
    """Advance one observed outcome; reject shortcuts and terminal retries.

    COMMIT_CONFIRMED requires an actual successful database commit.
    ABORT_CONFIRMED requires confirmed absence of a committed change.
    PUBLICATION_DURABLE requires successful anchor replacement and
    file/directory synchronization. Re-reading a file alone does not
    establish that an earlier durability failure has been resolved.
    """
    if not isinstance(state, PublicationState):
        raise TypeError("PublicationState required")
    if not isinstance(event, PublicationEvent):
        raise TypeError("PublicationEvent required")
    try:
        return _TRANSITIONS[(state, event)]
    except KeyError:
        raise ValueError("Invalid publication transition") from None
