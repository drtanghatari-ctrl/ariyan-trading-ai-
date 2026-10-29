import json
import unittest
import uuid
from dataclasses import replace

from ariyan_trading.authorization_status import (
    AuthorizationStatus,
    AuthorizationStatusRecord,
)
from ariyan_trading.authorization_status_observation import (
    VERSION as OBS_VERSION,
    AuthorizationStatusObservation,
)
from ariyan_trading.authorization_status_history import (
    VERSION as HISTORY_VERSION,
    DOMAIN,
    AuthorizationStatusHistoryEntry,
    canonical_status_history_entry,
)
from ariyan_trading.authorization_status_history_decoder import (
    MAX_PAYLOAD_BYTES,
    decode_status_history_entry,
)


class AuthorizationStatusHistoryDecoderTests(unittest.TestCase):

    def setUp(self):
        status = AuthorizationStatusRecord(
            authorization_id=str(uuid.uuid4()),
            authority_id="authority-1",
            revision=1,
            status=AuthorizationStatus.ACTIVE,
        )

        observation = AuthorizationStatusObservation(
            version=OBS_VERSION,
            status_record=status,
            source_id="source-1",
            sequence=7,
            observed_at=100,
            valid_until=200,
        )

        self.entry = AuthorizationStatusHistoryEntry(
            version=HISTORY_VERSION,
            stream_id=str(uuid.uuid4()),
            history_sequence=1,
            observation=observation,
        )

        self.payload = canonical_status_history_entry(self.entry)

    def modified(self, change):
        record = json.loads(self.payload[len(DOMAIN):])
        change(record)
        return DOMAIN + json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def test_valid_roundtrip(self):
        self.assertEqual(
            decode_status_history_entry(self.payload),
            self.entry,
        )

    def test_deterministic_roundtrip(self):
        restored = decode_status_history_entry(self.payload)
        self.assertEqual(
            canonical_status_history_entry(restored),
            self.payload,
        )

    def test_nonbytes_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(
                self.payload.decode("ascii")
            )

    def test_wrong_domain_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(
                b"WRONG\x00" + self.payload[len(DOMAIN):]
            )

    def test_empty_json_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(DOMAIN)

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(
                DOMAIN + b"x" * MAX_PAYLOAD_BYTES
            )

    def test_malformed_json_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(DOMAIN + b"{")

    def test_duplicate_keys_rejected(self):
        raw = self.payload[len(DOMAIN):]
        duplicate = (
            b'{"version":"duplicate",'
            + raw[1:]
        )

        with self.assertRaises(ValueError):
            decode_status_history_entry(DOMAIN + duplicate)

    def test_extra_top_level_field_rejected(self):
        def change(record):
            record["unexpected"] = 1

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_missing_top_level_field_rejected(self):
        def change(record):
            del record["stream_id"]

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_extra_observation_field_rejected(self):
        def change(record):
            record["observation"]["unexpected"] = 1

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_extra_status_field_rejected(self):
        def change(record):
            record["observation"]["status_record"]["unexpected"] = 1

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_unknown_status_rejected(self):
        def change(record):
            record["observation"]["status_record"]["status"] = "approved"

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_boolean_sequence_rejected(self):
        def change(record):
            record["history_sequence"] = True

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_invalid_uuid_rejected(self):
        def change(record):
            record["stream_id"] = "invalid"

        with self.assertRaises(ValueError):
            decode_status_history_entry(self.modified(change))

    def test_noncanonical_spacing_rejected(self):
        raw = self.payload[len(DOMAIN):]
        spaced = raw.replace(b":", b": ", 1)

        with self.assertRaises(ValueError):
            decode_status_history_entry(DOMAIN + spaced)

    def test_noncanonical_key_order_rejected(self):
        record = json.loads(self.payload[len(DOMAIN):])
        reordered = json.dumps(
            record,
            sort_keys=False,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

        if reordered != self.payload[len(DOMAIN):]:
            with self.assertRaises(ValueError):
                decode_status_history_entry(DOMAIN + reordered)

    def test_status_change_roundtrip(self):
        record = replace(
            self.entry.observation.status_record,
            status=AuthorizationStatus.REVOKED,
        )
        observation = replace(
            self.entry.observation,
            status_record=record,
        )
        changed = replace(self.entry, observation=observation)

        self.assertEqual(
            decode_status_history_entry(
                canonical_status_history_entry(changed)
            ),
            changed,
        )

    def test_invalid_utf8_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(DOMAIN + b"\xff")

    def test_nonstandard_json_constant_rejected(self):
        with self.assertRaises(ValueError):
            decode_status_history_entry(
                DOMAIN + b'{"value":NaN}'
            )


if __name__ == "__main__":
    unittest.main()
