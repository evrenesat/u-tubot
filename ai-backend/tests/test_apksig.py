from __future__ import annotations

import json
import shutil
import struct
import zipfile
from pathlib import Path

import pytest

from utubot import apksig

FIXTURES = Path(__file__).parent / "fixtures"
TEST_CERT_SHA256 = "cf434ab77f7f706af4224aacf9dd43b9b75eea61cbb09d729c746667c8d8a6b3"
FIRST_DIGEST_BYTE_OFFSET = (
    50  # inside the signed digest, counted from the start of the signing block
)
VECTORS = json.loads((FIXTURES / "rsa-vectors.json").read_text())


def fixture_copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / "app.apk"
    shutil.copy(FIXTURES / name, target)
    return target


def flip_byte(path: Path, offset: int) -> None:
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))


def signing_block_start(path: Path) -> int:
    with path.open("rb") as fh:
        return apksig._locate(fh)[0].signing_block_start


def test_v2_signed_apk_verifies_and_reports_its_certificate(tmp_path):
    found = apksig.verify_apk(fixture_copy(tmp_path, "signed-v2.apk.bin"))
    assert found == [apksig.SignerCertificate("v2", TEST_CERT_SHA256)]


def test_v2_and_v3_blocks_are_both_verified(tmp_path):
    found = apksig.verify_apk(fixture_copy(tmp_path, "signed-v2-v3.apk.bin"))
    assert sorted((c.scheme, c.sha256) for c in found) == [
        ("v2", TEST_CERT_SHA256),
        ("v3", TEST_CERT_SHA256),
    ]


@pytest.mark.parametrize("name", ["signed-v2.apk.bin", "signed-v2-v3.apk.bin"])
def test_content_changed_after_signing_is_refused(tmp_path, name):
    apk = fixture_copy(tmp_path, name)
    flip_byte(apk, 0)
    with pytest.raises(apksig.SignatureError, match="changed after signing"):
        apksig.verify_apk(apk)


def test_central_directory_changed_after_signing_is_refused(tmp_path):
    apk = fixture_copy(tmp_path, "signed-v2.apk.bin")
    with apk.open("rb") as fh:
        layout = apksig._locate(fh)[0]
    flip_byte(apk, layout.central_directory_start + 10)
    with pytest.raises(apksig.SignatureError, match="changed after signing"):
        apksig.verify_apk(apk)


def test_signed_data_changed_breaks_the_signature(tmp_path):
    apk = fixture_copy(tmp_path, "signed-v2.apk.bin")
    flip_byte(apk, signing_block_start(apk) + FIRST_DIGEST_BYTE_OFFSET)
    with pytest.raises(apksig.SignatureError, match="does not verify"):
        apksig.verify_apk(apk)


def test_unsigned_zip_has_no_signing_block(tmp_path):
    plain = tmp_path / "plain.apk"
    with zipfile.ZipFile(plain, "w") as archive:
        archive.writestr("a.txt", "hello")
    with pytest.raises(apksig.SignatureError, match="v1-only"):
        apksig.verify_apk(plain)


def test_garbage_and_truncated_files_are_refused(tmp_path):
    garbage = tmp_path / "garbage.apk"
    garbage.write_bytes(b"not a zip at all" * 100)
    with pytest.raises(apksig.SignatureError, match="not a ZIP"):
        apksig.verify_apk(garbage)
    truncated = fixture_copy(tmp_path, "signed-v2.apk.bin")
    truncated.write_bytes(truncated.read_bytes()[:-30])
    with pytest.raises(apksig.SignatureError):
        apksig.verify_apk(truncated)


def test_missing_file_is_refused(tmp_path):
    with pytest.raises(apksig.SignatureError, match="cannot read"):
        apksig.verify_apk(tmp_path / "absent.apk")


def test_hostile_block_sizes_are_refused(tmp_path):
    apk = fixture_copy(tmp_path, "signed-v2.apk.bin")
    with apk.open("rb") as fh:
        layout = apksig._locate(fh)[0]
    data = bytearray(apk.read_bytes())
    footer_at = layout.central_directory_start - apksig.SIGNING_BLOCK_FOOTER_BYTES
    data[footer_at : footer_at + 8] = struct.pack("<Q", 1 << 40)
    apk.write_bytes(bytes(data))
    with pytest.raises(apksig.SignatureError, match="invalid size"):
        apksig.verify_apk(apk)


@pytest.fixture
def rsa_key():
    return apksig.rsa_public_key(bytes.fromhex(VECTORS["rsa_spki"]))


@pytest.mark.parametrize("hash_name", ["sha256", "sha512"])
def test_rsa_signature_vectors_from_openssl(rsa_key, hash_name):
    message = VECTORS["message"].encode()
    pkcs1 = bytes.fromhex(VECTORS[f"pkcs1_{hash_name}"])
    pss = bytes.fromhex(VECTORS[f"pss_{hash_name}"])
    assert apksig.verify_pkcs1(*rsa_key, message, pkcs1, hash_name)
    assert apksig.verify_pss(*rsa_key, message, pss, hash_name)


@pytest.mark.parametrize("hash_name", ["sha256", "sha512"])
def test_rsa_signatures_reject_other_messages_signatures_and_paddings(rsa_key, hash_name):
    message = VECTORS["message"].encode()
    pkcs1 = bytes.fromhex(VECTORS[f"pkcs1_{hash_name}"])
    pss = bytes.fromhex(VECTORS[f"pss_{hash_name}"])
    assert not apksig.verify_pkcs1(*rsa_key, message + b"!", pkcs1, hash_name)
    assert not apksig.verify_pss(*rsa_key, message + b"!", pss, hash_name)
    assert not apksig.verify_pkcs1(*rsa_key, message, pss, hash_name)
    assert not apksig.verify_pss(*rsa_key, message, pkcs1, hash_name)
    assert not apksig.verify_pkcs1(*rsa_key, message, pkcs1[:-1], hash_name)
    assert not apksig.verify_pss(*rsa_key, message, b"\xff" * len(pss), hash_name)


def test_non_rsa_keys_point_to_apksigner(rsa_key):
    with pytest.raises(apksig.SignatureError, match="apksigner_path"):
        apksig.rsa_public_key(bytes.fromhex(VECTORS["ec_spki"]))
