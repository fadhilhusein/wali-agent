"""Ed25519 key helpers for the guard.

Keys are exchanged as base64 of the raw 32 bytes. The private key stays inside the guard; the
environment receives only the public key. Errors never include key material.
"""

from __future__ import annotations

import base64
import binascii

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

_RAW_KEY_BYTES = 32


class KeyFormatError(ValueError):
    """Raised when an encoded key cannot be loaded."""


def encode_private_key(key: Ed25519PrivateKey) -> str:
    raw = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode("ascii")


def encode_public_key(key: Ed25519PublicKey) -> str:
    raw = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def generate_keypair() -> tuple[str, str]:
    """Return a new ``(private, public)`` pair, both base64 encoded."""
    private = Ed25519PrivateKey.generate()
    return encode_private_key(private), encode_public_key(private.public_key())


def _decode(encoded: str, kind: str) -> bytes:
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise KeyFormatError(f"The {kind} key is not valid base64.") from None
    if len(raw) != _RAW_KEY_BYTES:
        raise KeyFormatError(f"The {kind} key must be {_RAW_KEY_BYTES} bytes.")
    return raw


def load_private_key(encoded: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_decode(encoded, "private"))


def load_public_key(encoded: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_decode(encoded, "public"))


def public_key_of(private_encoded: str) -> str:
    """The encoded public key that belongs to an encoded private key."""
    return encode_public_key(load_private_key(private_encoded).public_key())
