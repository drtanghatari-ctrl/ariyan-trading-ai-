"""Verify a witness-signed receipt for a frozen validation plan."""

import argparse
import hashlib
import json
import re
from pathlib import Path

from .market_data import integer
from .validation_plan import MAX_TIMESTAMP_MS, _unique_object, load_plan, verify_plan

VERSION = "ARIYAN-A042-PLAN-WITNESS-V1"
MAX_RECEIPT_BYTES = 4096


def _hex_bytes(value, size, name):
    if type(value) is not str or len(value) != 2 * size or not re.fullmatch(r"[0-9a-f]+", value):
        raise ValueError(f"{name} must be {size} bytes encoded as lowercase hex")
    return bytes.fromhex(value)


def witness_payload(plan_sha256, observed_at_ms):
    """Return the domain-separated bytes a witness signs."""
    _hex_bytes(plan_sha256, 32, "plan_sha256")
    if integer(observed_at_ms, "observed_at_ms") > MAX_TIMESTAMP_MS:
        raise ValueError("Witness timestamp is outside the supported range")
    return f"{VERSION}\n{plan_sha256}\n{observed_at_ms}\n".encode("ascii")


def verify_witness_receipt(plan, receipt, *, witness_public_key_hex):
    """Check the signature, exact plan fingerprint and pre-window ordering."""
    plan = verify_plan(plan)
    if type(receipt) is not dict or receipt.keys() != {
        "version", "plan_sha256", "observed_at_ms", "signature_hex",
    } or receipt["version"] != VERSION:
        raise ValueError("Unsupported witness receipt")
    observed = receipt["observed_at_ms"]
    payload = witness_payload(receipt["plan_sha256"], observed)
    if receipt["plan_sha256"] != plan["plan_sha256"]:
        raise ValueError("Witness receipt refers to a different plan")
    if not plan["created_at_ms"] <= observed < plan["spec"]["window"]["start_ms"]:
        raise ValueError("Witness time must follow plan creation and precede the window")

    key = _hex_bytes(witness_public_key_hex, 32, "witness public key")
    signature = _hex_bytes(receipt["signature_hex"], 64, "witness signature")
    try:
        from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ValueError("Witness verification requires the cryptography package") from exc
    try:
        Ed25519PublicKey.from_public_bytes(key).verify(signature, payload)
    except InvalidSignature as exc:
        raise ValueError("Invalid witness signature for the supplied key") from exc
    except UnsupportedAlgorithm as exc:
        raise ValueError("Ed25519 verification is unavailable") from exc

    return {
        "version": VERSION,
        "status": "SIGNED_PRE_WINDOW_RECEIPT_VERIFIED",
        "plan_sha256": plan["plan_sha256"],
        "observed_at_ms": observed,
        "witness_public_key_sha256": hashlib.sha256(key).hexdigest(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--witness-public-key-hex", required=True,
                        help="Expected Ed25519 key obtained independently of the receipt")
    args = parser.parse_args(argv)
    try:
        plan = load_plan(args.plan)
        with args.receipt.open("rb") as stream:
            raw = stream.read(MAX_RECEIPT_BYTES + 1)
        if len(raw) > MAX_RECEIPT_BYTES:
            raise ValueError("Witness receipt exceeds 4 KiB")
        receipt = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        result = verify_witness_receipt(
            plan, receipt, witness_public_key_hex=args.witness_public_key_hex,
        )
    except (OSError, ValueError, ArithmeticError, RecursionError) as exc:
        parser.exit(2, f"Witness receipt rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
