"""A006 C2D-04B2C4A history writer-policy tests."""

import unittest
import uuid

from ariyan_trading.authorization_history_writer_policy import (
    DOMAIN,
    VERSION,
    WRITER_MODE,
    create_history_writer_policy,
    verify_history_writer_policy,
)
from ariyan_trading.authorization_status_history_commitment import (
    opening_history_commitment,
)


class HistoryWriterPolicyTests(unittest.TestCase):

    def setUp(self):
        self.stream_id = str(uuid.uuid4())
        self.digest = opening_history_commitment(self.stream_id)
        self.key = b"A" * 32

    def policy(self):
        return create_history_writer_policy(
            self.stream_id,
            0,
            self.digest,
            self.key,
        )

    def test_valid_policy(self):
        result = verify_history_writer_policy(
            self.policy(), self.key
        )

        self.assertEqual(result["stream_id"], self.stream_id)
        self.assertEqual(result["writer_mode"], WRITER_MODE)
        self.assertEqual(result["enrollment_sequence"], 0)

    def test_deterministic_policy(self):
        self.assertEqual(self.policy(), self.policy())

    def test_domain_separation(self):
        self.assertEqual(
            DOMAIN,
            b"ARIYAN-A006-AUTH-HISTORY-WRITER-POLICY-V1\x00",
        )
        self.assertNotEqual(
            DOMAIN,
            b"ARIYAN-A006-AUTH-HISTORY-ANCHOR-V1\x00",
        )

    def test_version(self):
        self.assertEqual(
            VERSION,
            "ARIYAN-A006-AUTH-HISTORY-WRITER-POLICY-V1",
        )

    def test_wrong_key_rejected(self):
        with self.assertRaises(ValueError):
            verify_history_writer_policy(
                self.policy(), b"B" * 32
            )

    def test_short_key_rejected(self):
        with self.assertRaises(ValueError):
            create_history_writer_policy(
                self.stream_id, 0, self.digest, b"A" * 31
            )

    def test_modified_stream_rejected(self):
        policy = self.policy()
        policy["stream_id"] = str(uuid.uuid4())

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_modified_sequence_rejected(self):
        policy = self.policy()
        policy["enrollment_sequence"] = 1

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_modified_digest_rejected(self):
        policy = self.policy()
        policy["enrollment_digest"] = "0" * 64

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_modified_mode_rejected(self):
        policy = self.policy()
        policy["writer_mode"] = "legacy"

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_extra_field_rejected(self):
        policy = self.policy()
        policy["unexpected"] = True

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_missing_field_rejected(self):
        policy = self.policy()
        del policy["mac"]

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_boolean_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_history_writer_policy(
                self.stream_id, True, self.digest, self.key
            )

    def test_negative_sequence_rejected(self):
        with self.assertRaises(ValueError):
            create_history_writer_policy(
                self.stream_id, -1, self.digest, self.key
            )

    def test_noncanonical_digest_rejected(self):
        with self.assertRaises(ValueError):
            create_history_writer_policy(
                self.stream_id,
                0,
                "ABCDEF" * 10 + "ABCD",
                self.key,
            )

    def test_noncanonical_mac_rejected(self):
        policy = self.policy()
        policy["mac"] = policy["mac"].upper()

        with self.assertRaises(ValueError):
            verify_history_writer_policy(policy, self.key)

    def test_non_dict_rejected(self):
        with self.assertRaises(ValueError):
            verify_history_writer_policy([], self.key)

    def test_cross_stream_policy_differs(self):
        other_stream = str(uuid.uuid4())
        other_digest = opening_history_commitment(other_stream)

        other = create_history_writer_policy(
            other_stream, 0, other_digest, self.key
        )

        self.assertNotEqual(
            self.policy()["mac"],
            other["mac"],
        )


if __name__ == "__main__":
    unittest.main()
