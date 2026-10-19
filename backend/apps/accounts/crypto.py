"""Application-level encryption of small secrets (TOTP keys) with AES-256-GCM.

Stored format: version byte (1) | 12-byte nonce | ciphertext+tag. The user id
is bound as associated data, so a ciphertext copied onto another user's row
does not decrypt. In production the key comes from a KMS (envelope
encryption); locally from MFA_ENCRYPTION_KEY.
"""

import base64
import os
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

_VERSION = b"\x01"


def _cipher() -> AESGCM:
    return AESGCM(base64.b64decode(settings.MFA_ENCRYPTION_KEY))


def encrypt_secret(plaintext: str, *, user_id: uuid.UUID) -> bytes:
    nonce = os.urandom(12)
    return _VERSION + nonce + _cipher().encrypt(nonce, plaintext.encode(), user_id.bytes)


def decrypt_secret(blob: bytes, *, user_id: uuid.UUID) -> str:
    blob = bytes(blob)
    if blob[:1] != _VERSION:
        raise ValueError("unknown secret format")
    nonce, ciphertext = blob[1:13], blob[13:]
    return _cipher().decrypt(nonce, ciphertext, user_id.bytes).decode()
