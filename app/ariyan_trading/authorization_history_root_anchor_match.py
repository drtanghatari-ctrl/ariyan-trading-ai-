"""A006 B4-B3B1: externally supplied root-anchor matching.

Pure comparison only. Caller-supplied pins are not authenticated.
No enrollment, storage, freshness, revocation enforcement,
writer admission, or trading authorization.
"""

import hmac
import re

from .authorization_history_root_enrollment import (
    validate_history_root_enrollment,
)
from .authorization_history_root_binding import ALGORITHM
from .authorization_validation import valid_name


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def matches_external_root_anchor(
    enrollment,
    root_authority_id,
    public_key_sha256,
):
    """Compare structural enrollment to an external identity/key pin.

    The caller is responsible for independently establishing and
    protecting the supplied pin. A match does not prove that.
    """
    if not validate_history_root_enrollment(enrollment):
        raise ValueError("Invalid root enrollment")

    if not valid_name(root_authority_id):
        raise ValueError("Invalid external root identity")

    if (
        type(public_key_sha256) is not str
        or _SHA256.fullmatch(public_key_sha256) is None
    ):
        raise ValueError("Invalid external root fingerprint")

    binding = enrollment.binding

    if binding.algorithm != ALGORITHM:
        return False

    return (
        hmac.compare_digest(
            binding.root_authority_id,
            root_authority_id,
        )
        and hmac.compare_digest(
            binding.public_key_sha256,
            public_key_sha256,
        )
    )
