"""Deterministic SHA-256 journal commitments.

These commitments detect mismatches against retained digests.
They do not provide independent cryptographic authentication.
"""

import hashlib


DOMAIN = b"ARIYAN-TRADING-A005-JOURNAL-V1"


def encode_fields(*fields):
    """Encode typed fields without concatenation ambiguity."""
    result = bytearray()

    for value in fields:
        if isinstance(value, int) and not isinstance(value, bool):
            tag = b"I"
            raw = str(value).encode("ascii")
        elif isinstance(value, str):
            tag = b"S"
            raw = value.encode("utf-8")
        else:
            raise TypeError(
                "Journal commitment fields must be str or int"
            )

        result.extend(tag)
        result.extend(len(raw).to_bytes(8, "big"))
        result.extend(raw)

    return bytes(result)


def opening_commitment(opening_cash):
    """Bind the chain to its declared opening cash."""
    payload = encode_fields("OPENING", opening_cash)

    return hashlib.sha256(
        DOMAIN + b"\x00" + payload
    ).hexdigest()


def entry_commitment(
    previous_digest,
    sequence,
    request_id,
    action,
    quantity,
    price,
    cash_delta,
    units_delta,
):
    """Commit one complete journal entry to its predecessor."""
    if (
        not isinstance(previous_digest, str)
        or len(previous_digest) != 64
    ):
        raise ValueError("Invalid previous commitment")

    try:
        previous = bytes.fromhex(previous_digest)
    except ValueError as exc:
        raise ValueError(
            "Invalid previous commitment"
        ) from exc

    payload = encode_fields(
        sequence,
        request_id,
        action,
        quantity,
        price,
        cash_delta,
        units_delta,
    )

    return hashlib.sha256(
        DOMAIN + b"\x01" + previous + payload
    ).hexdigest()
