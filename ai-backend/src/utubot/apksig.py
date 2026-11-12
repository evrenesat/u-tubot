"""Check an APK's signature in pure Python, for a backend that has no Android build-tools (`apksigner`).

It reads the APK Signing Block (APK Signature Scheme v2, v3 and v3.1), verifies every signer's signature over its signed data
(RSA keys, PKCS#1 v1.5 and PSS), recomputes the content digest of the APK and compares it with the signed one, checks that the
signer's key is the key of its certificate, and returns the SHA-256 of each signer's certificate. An APK that was changed after
signing, or whose block only borrows the certificate, is refused. ECDSA and DSA signatures are not supported here: use
`[app] apksigner_path` for such a key. APKs with only a v1 (JAR) signature cannot be checked either.
"""

from __future__ import annotations

import hashlib
import hmac
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

EOCD_SIGNATURE = b"PK\x05\x06"
EOCD_MIN_BYTES = 22
EOCD_COMMENT_MAX_BYTES = 0xFFFF
EOCD_CD_SIZE_AT = 12
EOCD_CD_OFFSET_AT = 16
EOCD_COMMENT_LENGTH_AT = 20
ZIP64_MARKER = 0xFFFFFFFF

SIGNING_BLOCK_MAGIC = b"APK Sig Block 42"
SIGNING_BLOCK_FOOTER_BYTES = 8 + len(SIGNING_BLOCK_MAGIC)
MAX_SIGNING_BLOCK_BYTES = 1 << 20

BLOCK_ID_V2 = 0x7109871A
BLOCK_ID_V3 = 0xF05368C0
BLOCK_ID_V3_1 = 0x1B93AD61
SCHEME_NAMES = {BLOCK_ID_V2: "v2", BLOCK_ID_V3: "v3", BLOCK_ID_V3_1: "v3.1"}
SDK_RANGE_BYTES = 8

CONTENT_CHUNK_BYTES = 1 << 20
CHUNK_PREFIX = b"\xa5"
ROOT_PREFIX = b"\x5a"

# Signature algorithm id -> (padding, hash). The same hash is used for the content digest.
SIGNATURE_ALGORITHMS = {
    0x0101: ("pss", "sha256"),
    0x0102: ("pss", "sha512"),
    0x0103: ("pkcs1", "sha256"),
    0x0104: ("pkcs1", "sha512"),
}
PKCS1_DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha512": bytes.fromhex("3051300d060960864801650304020305000440"),
}
RSA_OID = bytes.fromhex("2a864886f70d010101")
PSS_TRAILER = 0xBC
MGF1_COUNTER_BYTES = 4

DER_SEQUENCE = 0x30
DER_BIT_STRING = 0x03
DER_EXPLICIT_VERSION = 0xA0
DER_LONG_FORM = 0x80
DER_MAX_LENGTH_BYTES = 4
CERT_FIELDS_BEFORE_KEY = 5  # serial, signature algorithm, issuer, validity, subject


class SignatureError(Exception):
    """The APK is not validly signed, or cannot be checked here."""


@dataclass(frozen=True)
class SignerCertificate:
    scheme: str
    sha256: str


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def done(self) -> bool:
        return self.pos >= len(self.data)

    def take(self, count: int) -> bytes:
        if count < 0 or self.pos + count > len(self.data):
            raise SignatureError("the signing block is truncated")
        chunk = self.data[self.pos : self.pos + count]
        self.pos += count
        return chunk

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack("<Q", self.take(8))[0]

    def prefixed(self) -> bytes:
        return self.take(self.u32())

    def items(self) -> list[bytes]:
        """The length-prefixed items of a sequence."""
        found = []
        while not self.done():
            found.append(self.prefixed())
        return found


def _der_item(buf: bytes, pos: int) -> tuple[int, int, int]:
    """(tag, start of content, end of content) of the DER element at pos."""
    if pos + 2 > len(buf):
        raise SignatureError("malformed DER")
    tag, length, pos = buf[pos], buf[pos + 1], pos + 2
    if length & DER_LONG_FORM:
        size = length & ~DER_LONG_FORM
        if not 0 < size <= DER_MAX_LENGTH_BYTES or pos + size > len(buf):
            raise SignatureError("malformed DER length")
        length = int.from_bytes(buf[pos : pos + size], "big")
        pos += size
    if pos + length > len(buf):
        raise SignatureError("malformed DER length")
    return tag, pos, pos + length


def certificate_public_key(cert: bytes) -> bytes:
    """The SubjectPublicKeyInfo encoding inside an X.509 certificate."""
    _, start, _ = _der_item(cert, 0)
    _, tbs_start, _ = _der_item(cert, start)
    pos = tbs_start
    tag, _, end = _der_item(cert, pos)
    if tag == DER_EXPLICIT_VERSION:
        pos = end
    for _ in range(CERT_FIELDS_BEFORE_KEY):
        _, _, pos = _der_item(cert, pos)
    _, _, key_end = _der_item(cert, pos)
    return cert[pos:key_end]


def rsa_public_key(spki: bytes) -> tuple[int, int]:
    """(modulus, exponent) of an RSA SubjectPublicKeyInfo."""
    _, start, _ = _der_item(spki, 0)
    _, alg_start, alg_end = _der_item(spki, start)
    _, oid_start, oid_end = _der_item(spki, alg_start)
    if spki[oid_start:oid_end] != RSA_OID:
        raise SignatureError(
            "the signer's key is not an RSA key; use [app] apksigner_path to verify it"
        )
    tag, bits_start, bits_end = _der_item(spki, alg_end)
    if tag != DER_BIT_STRING:
        raise SignatureError("malformed public key")
    key = spki[bits_start + 1 : bits_end]
    _, key_start, _ = _der_item(key, 0)
    _, n_start, n_end = _der_item(key, key_start)
    _, e_start, e_end = _der_item(key, n_end)
    return int.from_bytes(key[n_start:n_end], "big"), int.from_bytes(key[e_start:e_end], "big")


def _mgf1(seed: bytes, length: int, hash_name: str) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.new(hash_name, seed + counter.to_bytes(MGF1_COUNTER_BYTES, "big")).digest()
        counter += 1
    return out[:length]


def _signature_value(n: int, e: int, signature: bytes) -> int | None:
    if len(signature) != (n.bit_length() + 7) // 8:
        return None
    value = int.from_bytes(signature, "big")
    return pow(value, e, n) if value < n else None


def verify_pkcs1(n: int, e: int, message: bytes, signature: bytes, hash_name: str) -> bool:
    recovered = _signature_value(n, e, signature)
    if recovered is None:
        return False
    size = (n.bit_length() + 7) // 8
    info = PKCS1_DIGEST_INFO[hash_name] + hashlib.new(hash_name, message).digest()
    if size < len(info) + 11:
        return False
    expected = b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info
    return hmac.compare_digest(recovered.to_bytes(size, "big"), expected)


def verify_pss(n: int, e: int, message: bytes, signature: bytes, hash_name: str) -> bool:
    """RSASSA-PSS with MGF1 of the same hash and a salt as long as the hash (what Android uses)."""
    recovered = _signature_value(n, e, signature)
    if recovered is None:
        return False
    digest_size = hashlib.new(hash_name).digest_size
    em_bits = n.bit_length() - 1
    em_len = (em_bits + 7) // 8
    if recovered.bit_length() > em_bits or em_len < 2 * digest_size + 2:
        return False
    em = recovered.to_bytes(em_len, "big")
    if em[-1] != PSS_TRAILER:
        return False
    masked = em[: em_len - digest_size - 1]
    expected_hash = em[em_len - digest_size - 1 : -1]
    spare_bits = 8 * em_len - em_bits
    if spare_bits and masked[0] >> (8 - spare_bits):
        return False
    block = bytearray(
        a ^ b for a, b in zip(masked, _mgf1(expected_hash, len(masked), hash_name), strict=True)
    )
    if spare_bits:
        block[0] &= 0xFF >> spare_bits
    padding = em_len - 2 * digest_size - 2
    if bytes(block[:padding]) != b"\x00" * padding or block[padding] != 1:
        return False
    salt = bytes(block[-digest_size:])
    message_hash = hashlib.new(hash_name, message).digest()
    return hmac.compare_digest(
        hashlib.new(hash_name, b"\x00" * 8 + message_hash + salt).digest(), expected_hash
    )


@dataclass
class _Layout:
    size: int
    signing_block_start: int
    central_directory_start: int
    eocd_start: int


def _locate(fh: BinaryIO) -> tuple[_Layout, bytes]:
    """Where the signing block, the central directory and the end record sit, and the signing block itself."""
    fh.seek(0, 2)
    size = fh.tell()
    tail_start = max(0, size - EOCD_MIN_BYTES - EOCD_COMMENT_MAX_BYTES)
    fh.seek(tail_start)
    tail = fh.read()
    eocd_start = None
    for at in range(len(tail) - EOCD_MIN_BYTES, -1, -1):
        if tail[at : at + 4] != EOCD_SIGNATURE:
            continue
        comment_length = struct.unpack_from("<H", tail, at + EOCD_COMMENT_LENGTH_AT)[0]
        if at + EOCD_MIN_BYTES + comment_length == len(tail):
            eocd_start = tail_start + at
            break
    if eocd_start is None:
        raise SignatureError("not a ZIP archive")
    eocd = tail[eocd_start - tail_start :]
    (cd_start,) = struct.unpack_from("<I", eocd, EOCD_CD_OFFSET_AT)
    (cd_size,) = struct.unpack_from("<I", eocd, EOCD_CD_SIZE_AT)
    if ZIP64_MARKER in (cd_start, cd_size) or cd_start + cd_size != eocd_start:
        raise SignatureError("unsupported or inconsistent ZIP layout")
    if cd_start < SIGNING_BLOCK_FOOTER_BYTES:
        raise SignatureError("no APK Signing Block (a v1-only APK cannot be verified here)")
    fh.seek(cd_start - SIGNING_BLOCK_FOOTER_BYTES)
    footer = fh.read(SIGNING_BLOCK_FOOTER_BYTES)
    if footer[8:] != SIGNING_BLOCK_MAGIC:
        raise SignatureError("no APK Signing Block (a v1-only APK cannot be verified here)")
    block_size = struct.unpack("<Q", footer[:8])[0]
    if not SIGNING_BLOCK_FOOTER_BYTES <= block_size + 8 <= min(MAX_SIGNING_BLOCK_BYTES, cd_start):
        raise SignatureError("the APK Signing Block has an invalid size")
    block_start = cd_start - block_size - 8
    fh.seek(block_start)
    block = fh.read(block_size + 8)
    if struct.unpack("<Q", block[:8])[0] != block_size:
        raise SignatureError("the APK Signing Block sizes disagree")
    return _Layout(size, block_start, cd_start, eocd_start), block


def _content_digest(fh: BinaryIO, layout: _Layout, hash_name: str) -> bytes:
    """The chunked digest of the three signed sections of the APK: entries, central directory, end record."""
    fh.seek(layout.eocd_start)
    eocd = bytearray(fh.read())
    struct.pack_into("<I", eocd, EOCD_CD_OFFSET_AT, layout.signing_block_start)
    sections: list[tuple[int, int] | bytes] = [
        (0, layout.signing_block_start),
        (layout.central_directory_start, layout.eocd_start),
        bytes(eocd),
    ]
    chunk_digests = []
    for section in sections:
        if isinstance(section, bytes):
            pieces = (
                section[at : at + CONTENT_CHUNK_BYTES]
                for at in range(0, len(section), CONTENT_CHUNK_BYTES)
            )
        else:
            pieces = _read_chunks(fh, *section)
        for piece in pieces:
            chunk = hashlib.new(hash_name, CHUNK_PREFIX + struct.pack("<I", len(piece)) + piece)
            chunk_digests.append(chunk.digest())
    root = hashlib.new(
        hash_name, ROOT_PREFIX + struct.pack("<I", len(chunk_digests)) + b"".join(chunk_digests)
    )
    return root.digest()


def _read_chunks(fh: BinaryIO, start: int, end: int):
    fh.seek(start)
    remaining = end - start
    while remaining > 0:
        piece = fh.read(min(CONTENT_CHUNK_BYTES, remaining))
        if not piece:
            raise SignatureError("the APK ended early")
        remaining -= len(piece)
        yield piece


def _scheme_signers(block: bytes) -> dict[int, list[bytes]]:
    pairs = _Reader(block[8:-SIGNING_BLOCK_FOOTER_BYTES])
    found: dict[int, list[bytes]] = {}
    while not pairs.done():
        length = pairs.u64()
        pair = _Reader(pairs.take(length))
        block_id = pair.u32()
        if block_id in SCHEME_NAMES:
            found.setdefault(block_id, []).extend(_Reader(pair.prefixed()).items())
    return found


def _verify_signer(fh: BinaryIO, layout: _Layout, block_id: int, signer: bytes) -> bytes:
    """Verify one signer and return its certificate (DER)."""
    reader = _Reader(signer)
    signed_data = reader.prefixed()
    if block_id != BLOCK_ID_V2:
        reader.take(SDK_RANGE_BYTES)
    signatures = _Reader(reader.prefixed()).items()
    public_key = reader.prefixed()

    data = _Reader(signed_data)
    signed_digests = {}
    for item in _Reader(data.prefixed()).items():
        entry = _Reader(item)
        algorithm = entry.u32()
        signed_digests[algorithm] = entry.prefixed()
    certificates = _Reader(data.prefixed()).items()
    if not certificates:
        raise SignatureError("the signer carries no certificate")
    if certificate_public_key(certificates[0]) != public_key:
        raise SignatureError("the signer's key is not the key of its certificate")

    n, e = rsa_public_key(public_key)
    verified = 0
    digests: dict[str, bytes] = {}
    for item in signatures:
        entry = _Reader(item)
        algorithm, signature = entry.u32(), entry.prefixed()
        if algorithm not in SIGNATURE_ALGORITHMS:
            continue
        padding, hash_name = SIGNATURE_ALGORITHMS[algorithm]
        check = verify_pss if padding == "pss" else verify_pkcs1
        if not check(n, e, signed_data, signature, hash_name):
            raise SignatureError("a signature does not verify")
        if algorithm not in signed_digests:
            raise SignatureError("the signed data has no digest for a signature algorithm")
        if hash_name not in digests:
            digests[hash_name] = _content_digest(fh, layout, hash_name)
        if not hmac.compare_digest(digests[hash_name], signed_digests[algorithm]):
            raise SignatureError(
                "the APK content does not match the signed digest (changed after signing)"
            )
        verified += 1
    if not verified:
        raise SignatureError(
            "no supported signature algorithm (RSA only here); use [app] apksigner_path"
        )
    return certificates[0]


def verify_apk(path: Path) -> list[SignerCertificate]:
    """Verify the signatures of the APK and return the signing certificate of every signer of every scheme."""
    try:
        with path.open("rb") as fh:
            layout, block = _locate(fh)
            schemes = _scheme_signers(block)
            if (
                BLOCK_ID_V2 not in schemes
                and BLOCK_ID_V3 not in schemes
                and BLOCK_ID_V3_1 not in schemes
            ):
                raise SignatureError("the APK Signing Block has no v2 or v3 signature")
            found = []
            for block_id, signers in schemes.items():
                if not signers:
                    raise SignatureError(
                        f"the {SCHEME_NAMES[block_id]} signature block has no signer"
                    )
                for signer in signers:
                    cert = _verify_signer(fh, layout, block_id, signer)
                    found.append(
                        SignerCertificate(SCHEME_NAMES[block_id], hashlib.sha256(cert).hexdigest())
                    )
            return found
    except (OSError, struct.error, IndexError) as exc:
        raise SignatureError(f"cannot read the APK: {type(exc).__name__}") from exc
