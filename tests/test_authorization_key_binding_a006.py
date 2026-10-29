import unittest
from dataclasses import replace

from ariyan_trading.authorization_key_binding import (
    AuthorizationKeyBinding,
    VERSION,
    PURPOSE,
    validate_authorization_key_binding,
)


class AuthorizationKeyBindingTests(unittest.TestCase):

    def setUp(self):
        self.binding = AuthorizationKeyBinding(
            version=VERSION,
            authority_id="authority-1",
            key_id="key-1",
            purpose=PURPOSE,
            key=b"K" * 32,
        )

    def test_valid_structure(self):
        self.assertTrue(
            validate_authorization_key_binding(self.binding)
        )

    def test_wrong_version(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, version="wrong")
            )
        )

    def test_invalid_authority(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, authority_id="")
            )
        )

    def test_invalid_key_id(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, key_id=" key-1")
            )
        )

    def test_wrong_purpose(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, purpose="writer-policy")
            )
        )

    def test_short_key(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, key=b"K" * 31)
            )
        )

    def test_wrong_key_type(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, key="secret")
            )
        )

    def test_wrong_object_type(self):
        self.assertFalse(
            validate_authorization_key_binding(None)
        )

    def test_boolean_or_noncanonical_fields(self):
        self.assertFalse(
            validate_authorization_key_binding(
                replace(self.binding, version=True)
            )
        )

    def test_repr_redacts_key(self):
        displayed = repr(self.binding)
        self.assertIn("key=<redacted>", displayed)
        self.assertNotIn(repr(self.binding.key), displayed)

    def test_frozen(self):
        with self.assertRaises(AttributeError):
            self.binding.key_id = "replacement"


if __name__ == "__main__":
    unittest.main()
