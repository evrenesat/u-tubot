"""Password hashing for web sign-in: scrypt from the standard library, parameters stored in the hash."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

from .config import SecurityConfig

SCHEME = "scrypt"
SALT_BYTES = 16
KEY_BYTES = 32
MAXMEM_FACTOR = 2
MIN_N = 2**4
MAX_N = 2**20
MAX_R = 32
MAX_P = 16
DUMMY_PASSWORD = "utubot-dummy-password"


class PasswordError(ValueError):
    pass


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode(), validate=True)


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=KEY_BYTES,
        maxmem=MAXMEM_FACTOR * 128 * n * r + 128 * r * p * MAXMEM_FACTOR,
    )


def hash_password(password: str, sec: SecurityConfig) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, sec.scrypt_n, sec.scrypt_r, sec.scrypt_p)
    return f"{SCHEME}${sec.scrypt_n}${sec.scrypt_r}${sec.scrypt_p}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check; a malformed stored hash never matches."""
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != SCHEME:
            return False
        n_i, r_i, p_i = int(n), int(r), int(p)
        if not (MIN_N <= n_i <= MAX_N) or n_i & (n_i - 1) or not (1 <= r_i <= MAX_R):
            return False
        if not 1 <= p_i <= MAX_P:
            return False
        expected = _unb64(key)
        actual = _derive(password, _unb64(salt), n_i, r_i, p_i)
    except (ValueError, binascii.Error, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str, sec: SecurityConfig) -> bool:
    """True when the hash was made with a weaker cost than the configured one."""
    try:
        _, n, r, p, _, _ = stored.split("$")
        return int(n) < sec.scrypt_n or int(r) < sec.scrypt_r or int(p) < sec.scrypt_p
    except ValueError:
        return False


def dummy_hash(sec: SecurityConfig) -> str:
    """A hash to verify against when the user is unknown, so the timing does not tell."""
    return hash_password(DUMMY_PASSWORD, sec)


def check_strength(password: str, sec: SecurityConfig) -> None:
    if not isinstance(password, str) or len(password) < sec.password_min_chars:
        raise PasswordError(f"password must have at least {sec.password_min_chars} characters")
    if len(password) > sec.password_max_chars:
        raise PasswordError(f"password must have at most {sec.password_max_chars} characters")
