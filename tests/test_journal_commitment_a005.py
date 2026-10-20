import unittest

from ariyan_trading.journal_commitment import (
    encode_fields,
    opening_commitment,
    entry_commitment,
)


class JournalCommitmentA005Tests(unittest.TestCase):

    def make_entry(self, previous, **changes):
        fields = {
            "sequence": 1,
            "request_id": "buy-001",
            "action": "BUY",
            "quantity": "2",
            "price": "10",
            "cash_delta": "-20",
            "units_delta": "2",
        }
        fields.update(changes)
        return entry_commitment(previous, **fields)

    def test_deterministic_encoding(self):
        first = encode_fields(1, "BUY", "2")
        second = encode_fields(1, "BUY", "2")
        self.assertEqual(first, second)

    def test_field_boundaries_are_unambiguous(self):
        self.assertNotEqual(
            encode_fields("ab", "c"),
            encode_fields("a", "bc"),
        )
        self.assertNotEqual(
            encode_fields(1),
            encode_fields("1"),
        )

    def test_transaction_rewrite_changes_digest(self):
        previous = opening_commitment("100.00")
        original = self.make_entry(previous)
        altered = self.make_entry(
            previous,
            quantity="1",
            cash_delta="-10",
            units_delta="1",
        )
        self.assertNotEqual(original, altered)

    def test_predecessor_changes_digest(self):
        previous_a = opening_commitment("100.00")
        previous_b = opening_commitment("200.00")
        self.assertNotEqual(
            self.make_entry(previous_a),
            self.make_entry(previous_b),
        )

    def test_opening_balance_changes_digest(self):
        self.assertNotEqual(
            opening_commitment("100.00"),
            opening_commitment("200.00"),
        )

    def test_field_order_changes_encoding(self):
        self.assertNotEqual(
            encode_fields("BUY", "SELL"),
            encode_fields("SELL", "BUY"),
        )

    def test_invalid_previous_digest_rejected(self):
        with self.assertRaises(ValueError):
            self.make_entry("invalid")

    def test_unsupported_field_type_rejected(self):
        with self.assertRaises(TypeError):
            encode_fields(1.5)


if __name__ == "__main__":
    unittest.main()
