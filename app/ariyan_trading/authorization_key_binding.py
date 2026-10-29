"""A006 P3C12-B6C2-A: authorization key-binding contract.

Structural validation only.

No independent key provisioning, trusted storage,
key rotation, revocation, freshness, or trading authorization.
"""

from dataclasses import dataclass
from ariyan_trading.authorization_validation import valid_name

VERSION = "ARIYAN-A006-AUTH-KEY-BINDING-V1"
PURPOSE = "authorization-evidence-mac-v1"


@dataclass(frozen=True, repr=False)
class AuthorizationKeyBinding:
    version: str
    authority_id: str
    key_id: str
    purpose: str
    key: bytes

    def __repr__(self):
        return (
            "AuthorizationKeyBinding("
            f"version={self.version!r}, "
            f"authority_id={self.authority_id!r}, "
            f"key_id={self.key_id!r}, "
            f"purpose={self.purpose!r}, "
            "key=<redacted>)"
        )


def validate_authorization_key_binding(binding):
    """Validate structure; never establish independent trust."""

    if type(binding) is not AuthorizationKeyBinding:
        return False

    return (
        type(binding.version) is str
        and binding.version == VERSION
        and valid_name(binding.authority_id)
        and valid_name(binding.key_id)
        and type(binding.purpose) is str
        and binding.purpose == PURPOSE
        and type(binding.key) is bytes
        and len(binding.key) >= 32
    )
