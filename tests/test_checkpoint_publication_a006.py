"""A006 publication ordering and uncertainty boundaries."""

import unittest

from ariyan_trading.checkpoint_publication import (
    PublicationEvent as Event,
    PublicationState as State,
    advance_publication as advance,
)


class PublicationA006Tests(unittest.TestCase):
    def test_success_requires_commit_then_publication(self):
        state = advance(State.READY, Event.COMMIT_CONFIRMED)
        state = advance(state, Event.PUBLICATION_STARTED)
        state = advance(state, Event.PUBLICATION_DURABLE)
        self.assertIs(state, State.DURABLE)

    def test_publication_cannot_precede_commit(self):
        for event in (
            Event.PUBLICATION_STARTED,
            Event.PUBLICATION_DURABLE,
        ):
            with self.subTest(event=event):
                with self.assertRaises(ValueError):
                    advance(State.READY, event)

    def test_commit_alone_cannot_claim_durability(self):
        with self.assertRaises(ValueError):
            advance(State.COMMITTED, Event.PUBLICATION_DURABLE)

    def test_confirmed_abort_is_only_precommit(self):
        self.assertIs(
            advance(State.READY, Event.ABORT_CONFIRMED),
            State.CANCELLED,
        )
        for state in (State.COMMITTED, State.PUBLISHING):
            with self.subTest(state=state):
                with self.assertRaises(ValueError):
                    advance(state, Event.ABORT_CONFIRMED)

    def test_interruption_at_each_active_boundary_is_uncertain(self):
        for state in (State.READY, State.COMMITTED, State.PUBLISHING):
            with self.subTest(state=state):
                self.assertIs(
                    advance(state, Event.OUTCOME_UNCERTAIN),
                    State.UNCERTAIN,
                )

    def test_terminal_states_cannot_retry_or_self_certify(self):
        for state in (State.UNCERTAIN, State.CANCELLED, State.DURABLE):
            for event in Event:
                with self.subTest(state=state, event=event):
                    with self.assertRaises(ValueError):
                        advance(state, event)

    def test_untyped_inputs_are_rejected(self):
        for state, event in (
            ("READY", Event.COMMIT_CONFIRMED),
            (State.READY, "COMMIT_CONFIRMED"),
            (None, Event.COMMIT_CONFIRMED),
            (State.READY, True),
        ):
            with self.subTest(state=state, event=event):
                with self.assertRaises(TypeError):
                    advance(state, event)


if __name__ == "__main__":
    unittest.main()
