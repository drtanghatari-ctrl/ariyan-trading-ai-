"""Verify an RFC 3161 timestamp for a frozen validation plan offline."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from .validation_plan import load_plan, verify_plan

VERSION = "ARIYAN-A045-PLAN-TIMESTAMP-V1"
MAX_INPUT_BYTES = 256 * 1024
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _read_input(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_INPUT_BYTES + 1)
    if not 0 < len(data) <= MAX_INPUT_BYTES:
        raise ValueError("Timestamp input must be nonempty and at most 256 KiB")
    return data


def _openssl(*args):
    try:
        result = subprocess.run(
            ["openssl", "ts", *args], capture_output=True, timeout=15,
            env={**os.environ, "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("OpenSSL timestamp command timed out") from exc
    if result.returncode:
        raise ValueError(f"OpenSSL timestamp {args[0].removeprefix('-')} failed")
    return result.stdout.decode("ascii", errors="replace")


def _signed_time_ms(reply_text):
    if re.findall(r"^Hash Algorithm: (.*)$", reply_text, re.MULTILINE) != ["sha256"]:
        raise ValueError("Expected a SHA-256 timestamp")
    stamps = re.findall(r"^Time stamp: (.*)$", reply_text, re.MULTILINE)
    if len(stamps) != 1:
        raise ValueError("Expected one signed timestamp")
    match = re.fullmatch(
        r"([A-Za-z]{3}) +([0-9]{1,2}) ([0-9]{2}):([0-9]{2}):([0-9]{2})"
        r"(?:\.([0-9]+))? ([0-9]{4}) GMT", stamps[0],
    )
    if match is None:
        raise ValueError("Unsupported signed timestamp format")
    month, day, hour, minute, second, fraction, year = match.groups()
    utc = datetime(
        int(year), MONTHS.index(month) + 1, int(day),
        int(hour), int(minute), int(second), tzinfo=timezone.utc,
    )
    # The plan boundaries are integer milliseconds, so flooring preserves ordering.
    return int(utc.timestamp()) * 1000 + int((fraction or "").ljust(3, "0")[:3])


def verify_plan_timestamp(plan_path, receipt_path, ca_path, *, expected_ca_sha256,
                          tsa_cert_path=None):
    """Load a frozen plan and verify its timestamp response."""
    return verify_timestamp(
        load_plan(plan_path), receipt_path, ca_path,
        expected_ca_sha256=expected_ca_sha256, tsa_cert_path=tsa_cert_path,
    )


def verify_timestamp(plan, receipt_path, ca_path, *, expected_ca_sha256,
                     tsa_cert_path=None):
    """Check the signed digest and UTC time for the supplied plan snapshot."""
    plan = verify_plan(plan)
    ca = _read_input(ca_path)
    ca_digest = hashlib.sha256(ca).hexdigest()
    if ca_digest != expected_ca_sha256:
        raise ValueError("Timestamp CA file does not match the expected SHA-256")
    receipt = _read_input(receipt_path)
    with TemporaryDirectory(prefix="atai-timestamp-") as directory:
        root = Path(directory)
        ca_copy = root / "ca.pem"
        reply = root / "receipt.tsr"
        ca_copy.write_bytes(ca)
        reply.write_bytes(receipt)
        args = ["-CAfile", str(ca_copy)]
        if tsa_cert_path is not None:
            signer = root / "signer.pem"
            signer.write_bytes(_read_input(tsa_cert_path))
            args.extend(["-untrusted", str(signer)])
        _openssl("-verify", "-digest", plan["plan_sha256"], "-in", str(reply), *args)
        signed_ms = _signed_time_ms(_openssl("-reply", "-in", str(reply), "-text"))

    if not plan["created_at_ms"] <= signed_ms < plan["spec"]["window"]["start_ms"]:
        raise ValueError("Signed time must be at or after plan creation and before the window")
    return {
        "version": VERSION,
        "status": "RFC3161_PRE_WINDOW_TIMESTAMP_VERIFIED",
        "plan_sha256": plan["plan_sha256"],
        "signed_at_ms": signed_ms,
        "receipt_sha256": hashlib.sha256(receipt).hexdigest(),
        "ca_file_sha256": ca_digest,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--expected-ca-sha256", required=True)
    parser.add_argument("--tsa-cert", type=Path, help="Optional untrusted signer certificate")
    args = parser.parse_args(argv)
    try:
        result = verify_plan_timestamp(
            args.plan, args.receipt, args.ca_file,
            expected_ca_sha256=args.expected_ca_sha256, tsa_cert_path=args.tsa_cert,
        )
    except (OSError, ValueError, ArithmeticError, RecursionError) as exc:
        parser.exit(2, f"Plan timestamp rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
