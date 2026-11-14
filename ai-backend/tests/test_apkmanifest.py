from __future__ import annotations

import struct
from pathlib import Path

import pytest

from tests import axml
from utubot import apkmanifest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("utf8", [False, True])
def test_reads_the_root_attributes(tmp_path, utf8):
    apk = tmp_path / "a.apk"
    apk.write_bytes(axml.apk("dev.utubot.tv", 3001, "0.3.1", utf8=utf8))
    assert apkmanifest.read_apk_manifest(apk) == apkmanifest.ApkManifest(
        "dev.utubot.tv", 3001, "0.3.1"
    )


def test_a_missing_version_name_reads_as_empty(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(axml.apk("dev.utubot.tv", 7, None))
    assert apkmanifest.read_apk_manifest(apk).version_name == ""


def test_a_manifest_without_a_version_code_is_refused(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes(axml.apk("dev.utubot.tv", None, "1.0.0"))
    with pytest.raises(apkmanifest.ManifestError, match="no package or versionCode"):
        apkmanifest.read_apk_manifest(apk)


def test_plain_text_xml_is_not_binary_xml():
    with pytest.raises(apkmanifest.ManifestError, match="not binary XML"):
        apkmanifest.parse_manifest(b"<manifest package='x'/>")


def test_a_truncated_manifest_is_an_error_not_a_crash():
    data = axml.manifest_xml("dev.utubot.tv", 1, "1.0.0")
    end_element = 24  # the closing tag after the root element is not needed
    for cut in list(range(0, len(data) - end_element, 7)) + [len(data) - end_element - 1]:
        with pytest.raises(apkmanifest.ManifestError):
            apkmanifest.parse_manifest(data[:cut])


def test_a_chunk_claiming_more_than_the_file_holds_is_refused():
    data = bytearray(axml.manifest_xml("dev.utubot.tv", 1, "1.0.0"))
    data[12:16] = struct.pack("<I", 1 << 30)  # the string pool's size
    with pytest.raises(apkmanifest.ManifestError, match="corrupt chunk"):
        apkmanifest.parse_manifest(bytes(data))


def test_a_zip_without_a_manifest_is_refused(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes((FIXTURES / "signed-v2.apk.bin").read_bytes()[:10])
    with pytest.raises(apkmanifest.ManifestError):
        apkmanifest.read_apk_manifest(apk)


def test_reads_the_manifest_of_the_signed_fixture_apk_as_far_as_it_goes(tmp_path):
    apk = tmp_path / "a.apk"
    apk.write_bytes((FIXTURES / "signed-v2.apk.bin").read_bytes())
    with pytest.raises(apkmanifest.ManifestError, match="no package or versionCode"):
        apkmanifest.read_apk_manifest(apk)
