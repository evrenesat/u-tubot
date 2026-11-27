"""Authenticated encryption at rest for a user's own provider key.

A user stores their own OpenAI-compatible upstream key on the server (``user_providers.api_key``),
so it sits in the sqlite file just like the others. It is encrypted with a server secret kept in
the environment (``UTUBOT_PROVIDER_SECRET``), never in the repo or the database. The construction
is encrypt-then-MAC over an HMAC-SHA256 stream cipher: two 32-byte subkeys are derived from the
secret, a random 16-byte nonce frames a keystream, and a truncated HMAC authenticates
nonce||ciphertext. Nothing here depends on a third-party crypto package.

No secret is configured: the value is stored and returned as-is, so the file being 0600 is the
only protection and existing plain values stay readable. A stored value is marked (``MARKER``) when
it was encrypted, and a value that fails its MAC is refused rather than silently mis-decrypted (for
example after the secret was rotated).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

MARKER = "utb1:"
NONCE_BYTES = 16
TAG_BYTES = 16
_ENCRYPTION_KEY_MATERIAL = b"utubot-at-rest-enc"
_AUTH_KEY_MATERIAL = b"utubot-at-rest-mac"


def _subkeys(secret: str) -> tuple[bytes, bytes]:
    digest = hmac.new(secret.encode(), _ENCRYPTION_KEY_MATERIAL, hashlib.sha256).digest()
    return digest, hmac.new(secret.encode(), _AUTH_KEY_MATERIAL, hashlib.sha256).digest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks: list[bytes] = []
    block = 0
    while len(blocks) * 32 < length:
        blocks.append(hmac.new(key, nonce + block.to_bytes(8, "big"), hashlib.sha256).digest())
        block += 1
    return b"".join(blocks)[:length]


def _mac(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    return hmac.new(key, nonce + ciphertext, hashlib.sha256).digest()


def encrypt(secret: str, plaintext: str) -> str:
    """`plaintext` under `secret`; stored as-is when `secret` is empty."""
    if not secret:
        return plaintext
    enc_key, mac_key = _subkeys(secret)
    nonce = secrets.token_bytes(NONCE_BYTES)
    keystream = _keystream(enc_key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext.encode(), keystream, strict=False))
    tag = _mac(mac_key, nonce, ciphertext)[:TAG_BYTES]
    return MARKER + base64.b64encode(nonce + tag + ciphertext).decode()


def decrypt(secret: str, value: str) -> str:
    """Reverse of `encrypt`; a value without the marker or with a bad MAC is returned unchanged or
    refused respectively."""
    if not secret or not value.startswith(MARKER):
        return value
    enc_key, mac_key = _subkeys(secret)
    try:
        raw = base64.b64decode(value[len(MARKER) :].encode())
        nonce, tag, ciphertext = (
            raw[:NONCE_BYTES],
            raw[NONCE_BYTES : NONCE_BYTES + TAG_BYTES],
            raw[NONCE_BYTES + TAG_BYTES :],
        )
    except (ValueError, binascii.Error, IndexError):
        return value
    if not hmac.compare_digest(_mac(mac_key, nonce, ciphertext)[:TAG_BYTES], tag):
        raise ValueError("the stored provider key could not be decrypted")
    keystream = _keystream(enc_key, nonce, len(ciphertext))
    return bytes(a ^ b for a, b in zip(ciphertext, keystream, strict=False)).decode()
