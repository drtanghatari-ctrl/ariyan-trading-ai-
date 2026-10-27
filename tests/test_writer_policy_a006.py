"""A006-WB02 authenticated writer-policy tests."""

import copy
import hashlib
import hmac
import json
import unittest
import uuid

from ariyan_trading.writer_policy import (
    DOMAIN,
    VERSION,
    create_writer_policy,
    verify_writer_policy,
)


class WriterPolicyTests(unittest.TestCase):

    def setUp(self):
        self.key = b"K" * 32
        self.ledger_id = str(uuid.uuid4())
        self.digest = "ab" * 32
        self.policy = create_writer_policy(
            self.ledger_id,
            3,
            self.digest,
            self.key,
        )

    def test_domain_separator(self):
        self.assertEqual(
            DOMAIN,
            b"ARIYAN-A006-WRITER-POLICY-V1" + bytes([0]),
        )

    def test_valid_policy(self):
        verified = verify_writer_policy(
            self.policy, self.key
        )
        self.assertEqual(
            verified["ledger_id"], self.ledger_id
        )
        self.assertEqual(
            verified["writer_mode"], "managed-v1"
        )

    def test_deterministic_authentication(self):
        second = create_writer_policy(
            self.ledger_id, 3, self.digest, self.key
        )
        self.assertEqual(self.policy, second)

    def test_different_ledger_identity(self):
        other = create_writer_policy(
            str(uuid.uuid4()), 3, self.digest, self.key
        )
        self.assertNotEqual(
            self.policy["mac"], other["mac"]
        )

    def test_wrong_key_rejected(self):
        with self.assertRaises(ValueError):
            verify_writer_policy(
                self.policy, b"Z" * 32
            )

    def test_short_key_rejected(self):
        with self.assertRaises(ValueError):
            create_writer_policy(
                self.ledger_id, 3, self.digest, b"short"
            )

    def test_modified_fields_rejected(self):
        changes = {
            "ledger_id": str(uuid.uuid4()),
            "writer_mode": "legacy",
            "enrollment_sequence": 4,
            "enrollment_digest": "cd" * 32,
            "version": "unknown",
        }

        for field, replacement in changes.items():
            with self.subTest(field=field):
                altered = copy.deepcopy(self.policy)
                altered[field] = replacement

                with self.assertRaises(ValueError):
                    verify_writer_policy(
                        altered, self.key
                    )

    def test_extra_field_rejected(self):
        altered = dict(self.policy)
        altered["unexpected"] = True

        with self.assertRaises(ValueError):
            verify_writer_policy(altered, self.key)

    def test_missing_field_rejected(self):
        altered = dict(self.policy)
        del altered["mac"]

        with self.assertRaises(ValueError):
            verify_writer_policy(altered, self.key)

    def test_invalid_uuid_rejected(self):
        for value in (
            "not-a-uuid",
            str(uuid.uuid4()).upper(),
            str(uuid.uuid1()),
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    create_writer_policy(
                        value, 3, self.digest, self.key
                    )

    def test_invalid_sequence_rejected(self):
        for value in (True, -1, 1.5, "3"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    create_writer_policy(
                        self.ledger_id,
                        value,
                        self.digest,
                        self.key,
                    )

    def test_invalid_digest_rejected(self):
        for value in (
            "invalid",
            "AB" * 32,
            "00" * 31,
        ):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    create_writer_policy(
                        self.ledger_id, 3, value, self.key
                    )

    def test_cross_domain_mac_rejected(self):
        payload = {
            "version": VERSION,
            "ledger_id": self.ledger_id,
            "writer_mode": "managed-v1",
            "enrollment_sequence": 3,
            "enrollment_digest": self.digest,
        }

        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

        altered = dict(self.policy)
        altered["mac"] = hmac.new(
            self.key,
            encoded,
            hashlib.sha256,
        ).hexdigest()

        with self.assertRaises(ValueError):
            verify_writer_policy(altered, self.key)

    def test_noncanonical_mac_rejected(self):
        altered = dict(self.policy)
        altered["mac"] = altered["mac"].upper()

        with self.assertRaises(ValueError):
            verify_writer_policy(altered, self.key)


if __name__ == "__main__":
    unittest.main()
