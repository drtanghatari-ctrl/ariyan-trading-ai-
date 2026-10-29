import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_evidence import (
    AUTHORIZATION_EVIDENCE_VERSION,
    AuthorizationEvidence,
)
from ariyan_trading.authorization_key_binding import (
    AuthorizationKeyBinding,
    VERSION,
    PURPOSE,
)
from ariyan_trading.authorization_key_verification import (
    verify_bound_authorization,
)
from ariyan_trading.authorization_mac import (
    create_authorization_mac,
)
from ariyan_trading.writer_authorization import (
    WriterAuthorizationStatus as Status,
)


class AuthorizationKeyVerificationTests(unittest.TestCase):

    def setUp(self):
        self.evidence = AuthorizationEvidence(
            version=AUTHORIZATION_EVIDENCE_VERSION,
            authorization_id=str(uuid.uuid4()),
            ledger_id=str(uuid.uuid4()),
            writer_id="writer-1",
            authority_id="authority-1",
            revision=1,
            allowed_operations=("BUY",),
            valid_from=100,
            valid_until=200,
        )

        self.binding = AuthorizationKeyBinding(
            version=VERSION,
            authority_id="authority-1",
            key_id="key-1",
            purpose=PURPOSE,
            key=b"K" * 32,
        )

        self.mac = create_authorization_mac(
            self.evidence,
            self.binding.key,
        )

    def assess(self, evidence=None, mac=None, binding=None):
        return verify_bound_authorization(
            evidence=self.evidence if evidence is None else evidence,
            mac=self.mac if mac is None else mac,
            binding=self.binding if binding is None else binding,
        )

    def test_valid_mac_remains_uncertain(self):
        self.assertEqual(
            self.assess().status,
            Status.UNCERTAIN,
        )

    def test_wrong_key_denied(self):
        binding = replace(
            self.binding,
            key=b"Z" * 32,
        )
        self.assertEqual(
            self.assess(binding=binding).status,
            Status.DENY,
        )

    def test_authority_mismatch_denied(self):
        binding = replace(
            self.binding,
            authority_id="authority-2",
        )
        self.assertEqual(
            self.assess(binding=binding).status,
            Status.DENY,
        )

    def test_modified_evidence_denied(self):
        evidence = replace(
            self.evidence,
            revision=2,
        )
        self.assertEqual(
            self.assess(evidence=evidence).status,
            Status.DENY,
        )

    def test_invalid_evidence_denied(self):
        evidence = replace(
            self.evidence,
            revision=0,
        )
        self.assertEqual(
            self.assess(evidence=evidence).status,
            Status.DENY,
        )

    def test_invalid_binding_denied(self):
        binding = replace(
            self.binding,
            key=b"K" * 31,
        )
        self.assertEqual(
            self.assess(binding=binding).status,
            Status.DENY,
        )

    def test_invalid_mac_denied(self):
        self.assertEqual(
            self.assess(mac="invalid").status,
            Status.DENY,
        )

    def test_uppercase_mac_denied(self):
        self.assertEqual(
            self.assess(mac=self.mac.upper()).status,
            Status.DENY,
        )

    def test_attacker_controlled_key_never_allows(self):
        attacker_binding = replace(
            self.binding,
            key=b"A" * 32,
        )
        attacker_mac = create_authorization_mac(
            self.evidence,
            attacker_binding.key,
        )
        result = self.assess(
            binding=attacker_binding,
            mac=attacker_mac,
        )
        self.assertEqual(result.status, Status.UNCERTAIN)
        self.assertNotEqual(result.status, Status.ALLOW)

    def test_none_mac_denied(self):
        result = verify_bound_authorization(
            evidence=self.evidence,
            mac=None,
            binding=self.binding,
        )
        self.assertEqual(result.status, Status.DENY)

    def test_wrong_binding_type_denied(self):
        result = verify_bound_authorization(
            evidence=self.evidence,
            mac=self.mac,
            binding=None,
        )
        self.assertEqual(result.status, Status.DENY)


if __name__ == "__main__":
    unittest.main()
