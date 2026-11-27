import base64

import pytest

from utubot.at_rest import MARKER, decrypt, encrypt


def test_encrypt_then_decrypt_roundtrip():
    secret = "a-long-server-secret-value"
    value = encrypt(secret, "pk-secret-key")
    assert value != "pk-secret-key"
    assert value.startswith(MARKER)
    assert decrypt(secret, value) == "pk-secret-key"


def test_two_encryptions_of_the_same_value_differ():
    # a random nonce per call: the stored bytes must not be identical for the same key
    secret = "a-long-server-secret-value"
    a = encrypt(secret, "pk-secret-key")
    b = encrypt(secret, "pk-secret-key")
    assert a != b
    assert decrypt(secret, a) == "pk-secret-key"
    assert decrypt(secret, b) == "pk-secret-key"


def test_a_missing_secret_stores_the_value_plain():
    # no secret -> nothing to protect, the value stays as-is (backward compatible)
    assert encrypt("", "pk-secret-key") == "pk-secret-key"
    assert decrypt("", "pk-secret-key") == "pk-secret-key"


def test_a_wrong_secret_is_refused():
    secret = "the-real-secret"
    wrong = "a-different-secret-value"
    value = encrypt(secret, "pk-secret-key")
    with pytest.raises(ValueError):
        decrypt(wrong, value)


def test_a_tampered_value_fails_its_mac():
    secret = "a-long-server-secret-value"
    value = encrypt(secret, "pk-secret-key")
    # flip a byte in the decoded ciphertext body, then re-encode: the MAC no longer verifies
    raw = bytearray(base64.b64decode(value[len(MARKER) :]))
    raw[-1] ^= 0x01
    tampered = MARKER + base64.b64encode(bytes(raw)).decode()
    with pytest.raises(ValueError):
        decrypt(secret, tampered)


def test_a_value_without_the_marker_is_returned_unchanged():
    # an old plaintext value predates the marker and is returned as-is
    assert decrypt("a-long-server-secret-value", "pk-old-plaintext") == "pk-old-plaintext"


def test_a_value_for_a_different_secret_is_returned_unchanged():
    # the marker is present but this secret never encrypted it: refuse, do not mis-decrypt
    other = "some-other-secret"
    value = encrypt("the-encrypting-secret", "pk-secret-key")
    with pytest.raises(ValueError):
        decrypt(other, value)
