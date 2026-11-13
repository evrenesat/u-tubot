"""Read the package name, versionCode and versionName out of an APK's binary AndroidManifest.xml (no aapt2 needed).

`utubot app sync-github` cross-checks these against the release metadata, so a release.json that lies about the version (or
points at another app's APK signed with the same key) is refused before anything is published. Only the attributes of the
root <manifest> element are read; the rest of the binary XML is ignored.
"""

from __future__ import annotations

import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path

MANIFEST_NAME = "AndroidManifest.xml"
MAX_MANIFEST_BYTES = 8 << 20
MAX_STRINGS = 200_000

_CHUNK_XML = 0x0003
_CHUNK_STRING_POOL = 0x0001
_CHUNK_START_ELEMENT = 0x0102
_UTF8_FLAG = 0x100
_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11


class ManifestError(Exception):
    """The APK has no readable binary manifest."""


@dataclass
class ApkManifest:
    package: str
    version_code: int
    version_name: str


def _u16(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 2 > len(data):
        raise ManifestError("truncated binary manifest")
    return struct.unpack_from("<H", data, pos)[0]


def _u32(data: bytes, pos: int) -> int:
    if pos < 0 or pos + 4 > len(data):
        raise ManifestError("truncated binary manifest")
    return struct.unpack_from("<I", data, pos)[0]


def _length8(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos] if pos < len(data) else 0
    if first & 0x80:
        return ((first & 0x7F) << 8) | (data[pos + 1] if pos + 1 < len(data) else 0), 2
    return first, 1


def _length16(data: bytes, pos: int) -> tuple[int, int]:
    first = _u16(data, pos)
    if first & 0x8000:
        return ((first & 0x7FFF) << 16) | _u16(data, pos + 2), 4
    return first, 2


def _string_pool(data: bytes, start: int, size: int) -> list[str]:
    count = _u32(data, start + 8)
    flags = _u32(data, start + 16)
    strings_start = start + _u32(data, start + 20)
    header_size = _u16(data, start + 2)
    if count > MAX_STRINGS or start + header_size + count * 4 > start + size:
        raise ManifestError("implausible string pool in the binary manifest")
    utf8 = bool(flags & _UTF8_FLAG)
    strings = []
    for index in range(count):
        pos = strings_start + _u32(data, start + header_size + index * 4)
        if utf8:
            _, skip = _length8(data, pos)  # length in characters, not needed
            nbytes, skip2 = _length8(data, pos + skip)
            raw = data[pos + skip + skip2 : pos + skip + skip2 + nbytes]
            strings.append(raw.decode("utf-8", "replace"))
        else:
            nchars, skip = _length16(data, pos)
            raw = data[pos + skip : pos + skip + nchars * 2]
            strings.append(raw.decode("utf-16-le", "replace"))
    return strings


def parse_manifest(data: bytes) -> ApkManifest:
    """Parse a binary AndroidManifest.xml."""
    if _u16(data, 0) != _CHUNK_XML:
        raise ManifestError("AndroidManifest.xml is not binary XML")
    pos = _u16(data, 2)
    strings: list[str] = []
    while pos + 8 <= len(data):
        kind, header_size, size = _u16(data, pos), _u16(data, pos + 2), _u32(data, pos + 4)
        if size < 8 or pos + size > len(data):
            raise ManifestError("corrupt chunk in the binary manifest")
        if kind == _CHUNK_STRING_POOL:
            strings = _string_pool(data, pos, size)
        elif kind == _CHUNK_START_ELEMENT:
            body = pos + header_size
            name = _u32(data, body + 4)
            if name < len(strings) and strings[name] == "manifest":
                return _root_attributes(data, body, strings)
            raise ManifestError("the first element of AndroidManifest.xml is not <manifest>")
        pos += size
    raise ManifestError("AndroidManifest.xml has no <manifest> element")


def _root_attributes(data: bytes, body: int, strings: list[str]) -> ApkManifest:
    attr_start = _u16(data, body + 8)
    attr_size = _u16(data, body + 10)
    attr_count = _u16(data, body + 12)
    values: dict[str, str | int] = {}
    for index in range(attr_count):
        at = body + attr_start + index * attr_size
        name_index, raw_index = _u32(data, at + 4), _u32(data, at + 8)
        kind, number = data[at + 15] if at + 15 < len(data) else 0, _u32(data, at + 16)
        if name_index >= len(strings):
            continue
        name = strings[name_index]
        if kind == _TYPE_STRING:
            text = number if number < len(strings) else raw_index
            if text < len(strings):
                values[name] = strings[text]
        elif kind in (_TYPE_INT_DEC, _TYPE_INT_HEX):
            values[name] = number
    package, code, version_name = (
        values.get("package"),
        values.get("versionCode"),
        values.get("versionName"),
    )
    if not isinstance(package, str) or not isinstance(code, int):
        raise ManifestError("the manifest has no package or versionCode")
    return ApkManifest(package, code, version_name if isinstance(version_name, str) else "")


def read_apk_manifest(apk: Path) -> ApkManifest:
    """The package, versionCode and versionName declared by an APK."""
    try:
        with zipfile.ZipFile(apk) as zf:
            info = zf.getinfo(MANIFEST_NAME)
            if info.file_size > MAX_MANIFEST_BYTES:
                raise ManifestError(f"{MANIFEST_NAME} is implausibly large")
            data = zf.read(info)
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ManifestError(
            f"{apk.name} has no readable {MANIFEST_NAME}: {type(exc).__name__}"
        ) from exc
    return parse_manifest(data)
