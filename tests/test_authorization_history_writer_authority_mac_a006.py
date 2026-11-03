"""A006 C2D-04B2C4B4-B1 delegation authentication tests."""

import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_history_writer_authority import (
    VERSION as EVIDENCE_VERSION,
    APPEND_HISTORY,
    HistoryWriterAuthorityEvidence,
)
from ariyan_trading.authorization_history_writer_authority_mac import (
    DOMAIN,
    canonical_history_writer_authority_payload,
    create_history_writer_authority_mac,
    verify_history_writer_authority_mac,
)


KEY = b"K" * 32
WRONG_KEY = b"Z" * 32


class HistoryWriterAuthorityMacTests(unittest.TestCase):

    def setUp(self):
        self.evidence = HistoryWriterAuthorityEvidence(
            version=EVIDENCE_VERSION,
            authorization_id=str(uuid.uuid4()),
            root_authority_id="human-root-1",
            writer_id="history-writer-1",
            stream_id=str(uuid.uuid4()),
            revision=1,
            allowed_operations=(APPEND_HISTORY,),
            valid_from=100,
            valid_until=200,
            status_reference="root-status-1",
        )

    def test_valid_mac(self):
        mac = create_history_writer_authority_mac(
            self.evidence, KEY
        )
        self.assertTrue(
            verify_history_writer_authority_mac(
                self.evidence, mac, KEY
            )
        )

    def test_deterministic(self):
        first = create_history_writer_authority_mac(
            self.evidence, KEY
        )
        second = create_history_writer_authority_mac(
            self.evidence, KEY
        )
        self.assertEqual(first, second)

    def test_domain_separation(self):
        payload = canonical_history_writer_authority_payload(
            self.evidence
        )
        self.assertTrue(payload.startswith(DOMAIN))
        self.assertNotEqual(
            DOMAIN,
            b"ARIYAN-A006-AUTHORIZATION-MAC-V1\x00",
        )

    def test_wrong_key(self):
        mac = create_history_writer_authority_mac(
            self.evidence, KEY
        )
        self.assertFalse(
            verify_history_writer_authority_mac(
                self.evidence, mac, WRONG_KEY
            )
        )

    def test_tampering(self):
        mac = create_history_writer_authority_mac(
            self.evidence, KEY
        )

        changes = (
            {"root_authority_id": "human-root-2"},
            {"writer_id": "history-writer-2"},
            {"stream_id": str(uuid.uuid4())},
            {"authorization_id": str(uuid.uuid4())},
            {"revision": 2},
            {"valid_from": 101},
            {"valid_until": 201},
            {"status_reference": "root-status-2"},
        )

        for change in changes:
            with self.subTest(change=change):
                modified = replace(self.evidence, **change)
                self.assertFalse(
                    verify_history_writer_authority_mac(
                        modified, mac, KEY
                    )
                )

    def test_invalid_keys(self):
        for key in (None, "secret", b"short", bytearray(KEY)):
            with self.subTest(key=type(key).__name__):
                with self.assertRaises(ValueError):
                    create_history_writer_authority_mac(
                        self.evidence, key
                    )

    def test_invalid_mac_encoding(self):
        for mac in (
            None,
            True,
            "",
            "z" * 64,
            "A" * 64,
            "0" * 63,
        ):
            with self.subTest(mac=mac):
                with self.assertRaises(ValueError):
                    verify_history_writer_authority_mac(
                        self.evidence, mac, KEY
                    )

    def test_invalid_evidence(self):
        with self.assertRaises(ValueError):
            create_history_writer_authority_mac(
                replace(self.evidence, revision=0), KEY
            )

    def test_cross_domain_substitution(self):
        from ariyan_trading.authorization_mac import (
            create_authorization_mac,
        )
        from ariyan_trading.authorization_evidence import (
            AuthorizationEvidence,
            AUTHORIZATION_EVIDENCE_VERSION,
        )

        other = AuthorizationEvidence(
            version=AUTHORIZATION_EVIDENCE_VERSION,
            authorization_id=self.evidence.authorization_id,
            ledger_id=self.evidence.stream_id,
            writer_id=self.evidence.writer_id,
            authority_id=self.evidence.root_authority_id,
            revision=1,
            allowed_operations=("BUY",),
            valid_from=100,
            valid_until=200,
        )

        other_mac = create_authorization_mac(other, KEY)

        self.assertFalse(
            verify_history_writer_authority_mac(
                self.evidence, other_mac, KEY
            )
        )


if __name__ == "__main__":
    unittest.main()
