import unittest
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AuthorizationEvidence,
    AUTHORIZATION_EVIDENCE_VERSION,
)
from ariyan_trading.authorization_validation import (
    validate_authorization_evidence as valid,
)


class AuthorizationValidationTests(unittest.TestCase):

    def setUp(self):
        self.e = AuthorizationEvidence(
            AUTHORIZATION_EVIDENCE_VERSION,
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
            "writer-001",
            "authority-001",
            1,
            ("BUY", "SELL"),
            100,
            200,
        )

    def test_valid(self):
        self.assertTrue(valid(self.e))

    def test_wrong_object(self):
        self.assertFalse(valid(None))

    def test_invalid_identifiers(self):
        for field in ("authorization_id", "ledger_id"):
            with self.subTest(field=field):
                self.assertFalse(valid(replace(self.e, **{field: "bad"})))

    def test_invalid_names(self):
        for field in ("writer_id", "authority_id"):
            for name in ("", " bad", "bad\nname", "x" * 129):
                with self.subTest(field=field, name=name):
                    self.assertFalse(valid(replace(self.e, **{field: name})))

    def test_invalid_revision(self):
        for revision in (0, -1, True, "1"):
            self.assertFalse(valid(replace(self.e, revision=revision)))

    def test_invalid_operations(self):
        for ops in ((), ("BUY", "BUY"), ("HOLD",), ["BUY"]):
            with self.subTest(ops=ops):
                self.assertFalse(valid(replace(self.e, allowed_operations=ops)))

    def test_invalid_time(self):
        for start, end in ((100, 100), (200, 100), (-1, 200), (True, 200)):
            with self.subTest(start=start, end=end):
                self.assertFalse(valid(replace(self.e, valid_from=start, valid_until=end)))

    def test_wrong_version(self):
        self.assertFalse(valid(replace(self.e, version="unknown")))


if __name__ == "__main__":
    unittest.main()
