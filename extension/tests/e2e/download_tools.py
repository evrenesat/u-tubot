"""Downloads the pinned Firefox and geckodriver of tools.lock and verifies their SHA-256. This is the only download the
e2e runs make; afterwards everything is local.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
LOCK = HERE / "tools.lock"


def fetch(url: str, sha256: str) -> bytes:
    with urlopen(url) as response:  # noqa: S310 - the two pinned tool URLs only
        body = response.read()
    actual = hashlib.sha256(body).hexdigest()

    if actual != sha256:
        raise SystemExit(f"SHA-256 mismatch for {url}: {actual}")

    return body


def extract(body: bytes, destination: Path, *, xz: bool) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(body), mode="r:xz" if xz else "r:gz") as archive:
        archive.extractall(destination)


def main(destination: Path | None = None) -> None:
    destination = destination or HERE / ".tools"
    lock = json.loads(LOCK.read_text(encoding="utf-8"))

    firefox = lock["firefox"]
    extract(fetch(firefox["url"], firefox["sha256"]), destination, xz=True)

    geckodriver = lock["geckodriver"]
    extract(fetch(geckodriver["url"], geckodriver["sha256"]), destination, xz=False)


if __name__ == "__main__":
    main()
