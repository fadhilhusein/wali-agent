"""Canonical JSON and Ed25519 signatures over it.

The canonical form is JSON with sorted keys and no whitespace. Only JSON-native values are
accepted; floats are rejected because their text form is not stable, so money must already be a
string (which is what ``model_dump(mode="json")`` produces for ``Decimal``).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

SIGNATURE_PREFIX = "ed25519:"


def _check_canonical(value: Any, path: str = "$") -> None:
    if value is None or isinstance(value, str | bool | int):
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Non-string key at {path}")
            _check_canonical(item, f"{path}.{key}")
        return
    if isinstance(value, list | tuple):
        for index, item in enumerate(value):
            _check_canonical(item, f"{path}[{index}]")
        return
    raise TypeError(f"Value of type {type(value).__name__} at {path} is not canonical JSON")


def canonical_json(payload: Any) -> bytes:
    """Serialise ``payload`` deterministically. Raises ``TypeError`` for floats and other types."""
    _check_canonical(payload)
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def sign_payload(private_key: Ed25519PrivateKey, payload: Any) -> str:
    signature = private_key.sign(canonical_json(payload))
    return SIGNATURE_PREFIX + base64.b64encode(signature).decode("ascii")


def verify_payload(public_key: Ed25519PublicKey, payload: Any, signature: object) -> bool:
    """Return True only for a valid signature. Never raises: anything unexpected is False."""
    try:
        if not isinstance(signature, str) or not signature.startswith(SIGNATURE_PREFIX):
            return False
        raw = base64.b64decode(signature[len(SIGNATURE_PREFIX) :], validate=True)
        public_key.verify(raw, canonical_json(payload))
    except (InvalidSignature, binascii.Error, ValueError, TypeError):
        return False
    return True
