"""A006 C2D-04B2A publication-intent validation tests."""

import json
import unittest
from uuid import uuid4

from ariyan_trading.authorization_history_publication_intent import (
    VERSION,
    create_publication_intent,
    validate_publication_intent,
    canonical_publication_intent,
)


class PublicationIntentTests(unittest.TestCase):

    def setUp(self):
        self.stream_id = str(uuid4())
        self.digest = "a" * 64
        self.intent = create_publication_intent(
            self.stream_id, 1, self.digest
        )

    def test_valid_intent(self):
        self.assertTrue(
            validate_publication_intent(self.intent)
        )

    def test_canonical_serialization(self):
        encoded = canonical_publication_intent(self.intent)

        self.assertIsInstance(encoded, bytes)
        self.assertEqual(
            json.loads(encoded),
            self.intent,
        )

        self.assertEqual(
            encoded,
            json.dumps(
                self.intent,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii"),
        )

    def test_deterministic_serialization(self):
        reversed_intent = dict(
            reversed(list(self.intent.items()))
        )

        self.assertEqual(
            canonical_publication_intent(self.intent),
            canonical_publication_intent(reversed_intent),
        )

    def test_zero_sequence_allowed(self):
        intent = create_publication_intent(
            self.stream_id, 0, self.digest
        )
        self.assertTrue(validate_publication_intent(intent))

    def test_negative_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                self.stream_id, -1, self.digest
            )

    def test_boolean_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                self.stream_id, True, self.digest
            )

    def test_invalid_stream_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                "invalid-stream", 1, self.digest
            )

    def test_uppercase_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                self.stream_id, 1, "A" * 64
            )

    def test_short_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                self.stream_id, 1, "a" * 63
            )

    def test_nonhex_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_publication_intent(
                self.stream_id, 1, "z" * 64
            )

    def test_extra_field_rejected(self):
        modified = dict(self.intent)
        modified["unexpected"] = "value"

        with self.assertRaises(ValueError):
            validate_publication_intent(modified)

    def test_missing_field_rejected(self):
        modified = dict(self.intent)
        del modified["history_digest"]

        with self.assertRaises(ValueError):
            validate_publication_intent(modified)

    def test_wrong_version_rejected(self):
        modified = dict(self.intent)
        modified["version"] = VERSION + "-INVALID"

        with self.assertRaises(ValueError):
            validate_publication_intent(modified)

    def test_nondictionary_rejected(self):
        for value in (None, [], "", 123):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_publication_intent(value)


if __name__ == "__main__":
    unittest.main()
