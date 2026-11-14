"""Build a minimal APK (a zip with a binary AndroidManifest.xml) for the tests."""

from __future__ import annotations

import io
import struct
import zipfile


def _pool(strings: list[str], utf8: bool) -> bytes:
    blobs = []
    for text in strings:
        if utf8:
            raw = text.encode()
            blobs.append(bytes([len(text), len(raw)]) + raw + b"\0")
        else:
            blobs.append(struct.pack("<H", len(text)) + text.encode("utf-16-le") + b"\0\0")
    offsets, pos = [], 0
    for blob in blobs:
        offsets.append(pos)
        pos += len(blob)
    body = b"".join(blobs)
    body += b"\0" * (-len(body) % 4)
    header = 28
    strings_start = header + 4 * len(strings)
    size = strings_start + len(body)
    return (
        struct.pack(
            "<HHIIIIII", 1, header, size, len(strings), 0, 0x100 if utf8 else 0, strings_start, 0
        )
        + b"".join(struct.pack("<I", o) for o in offsets)
        + body
    )


def manifest_xml(
    package: str, version_code: int | None, version_name: str | None, *, utf8: bool = False
) -> bytes:
    names = ["package", "versionCode", "versionName", "manifest", package]
    if version_name is not None:
        names.append(version_name)
    pool = _pool(names, utf8)
    index = {n: i for i, n in enumerate(names)}
    attrs = [(index["package"], index[package], 3, index[package])]
    if version_code is not None:
        attrs.append((index["versionCode"], 0xFFFFFFFF, 0x10, version_code))
    if version_name is not None:
        attrs.append((index["versionName"], index[version_name], 3, index[version_name]))
    packed = b"".join(
        struct.pack("<IIIHBBI", 0xFFFFFFFF, name, raw, 8, 0, kind, data)
        for name, raw, kind, data in attrs
    )
    element = (
        struct.pack("<HHIII", 0x102, 16, 36 + len(packed), 1, 0xFFFFFFFF)
        + struct.pack("<IIHHHHHH", 0xFFFFFFFF, index["manifest"], 20, 20, len(attrs), 0, 0, 0)
        + packed
    )
    end = struct.pack("<HHIII", 0x103, 16, 24, 1, 0xFFFFFFFF) + struct.pack(
        "<II", 0xFFFFFFFF, index["manifest"]
    )
    total = 8 + len(pool) + len(element) + len(end)
    return struct.pack("<HHI", 3, 8, total) + pool + element + end


def apk(
    package: str,
    version_code: int | None,
    version_name: str | None,
    *,
    utf8: bool = False,
    extra: bytes = b"",
) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr(
            "AndroidManifest.xml", manifest_xml(package, version_code, version_name, utf8=utf8)
        )
        if extra:
            zf.writestr("payload.bin", extra)
    return out.getvalue()
