import unittest
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AuthorizationEvidence,
    AUTHORIZATION_EVIDENCE_VERSION,
)
from ariyan_trading.authorization_validation import (
    validate_authorization_evidence,
)


class AuthorizationHardeningTests(unittest.TestCase):

    def setUp(self):
        self.e = AuthorizationEvidence(
            AUTHORIZATION_EVIDENCE_VERSION,
            "123e4567-e89b-42d3-a456-426614174000",
            "123e4567-e89b-42d3-a456-426614174001",
            "writer-001",
            "authority-001",
            1,
            ("BUY",),
            100,
            200,
        )

    def test_nonstring_version_rejected(self):
        for value in (None, 1, True, b"version"):
            with self.subTest(value=value):
                self.assertFalse(
                    validate_authorization_evidence(
                        replace(self.e, version=value)
                    )
                )

    def test_malformed_unicode_rejected(self):
        for field in ("writer_id", "authority_id"):
            with self.subTest(field=field):
                self.assertFalse(
                    validate_authorization_evidence(
                        replace(self.e, **{field: "\ud800"})
                    )
                )


if __name__ == "__main__":
    unittest.main()
