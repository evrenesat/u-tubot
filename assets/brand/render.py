# /// script
# requires-python = ">=3.10"
# dependencies = ["cairosvg==2.9.1"]
# ///
"""Renders the SVG sources in this directory to the PNGs of the stutubot flavor and to previews.

Run from anywhere: `uv run assets/brand/render.py` (needs the cairo system library, e.g. `apt install libcairo2`).
The SVGs carry no fonts (the wordmark is drawn with paths), so the output does not depend on the machine.
The banner repeats the markup of the symbol and the wordmark (one file, no external references): the script stops when they differ.
"""
import re
import sys
from pathlib import Path

import cairosvg

BRAND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BRAND_DIR.parent.parent
FLAVOR_RES = REPO_ROOT / "smarttubetv" / "src" / "stutubot" / "res" / "mipmap-nodpi"
PREVIEW_DIR = BRAND_DIR / "png"

# (svg, destination, width, height, background): no background is transparent
INK = "#0F1124"
SYMBOL = "utubot-symbol.svg"
WORDMARK = "utubot-wordmark.svg"
BANNER = "utubot-banner.svg"
TARGETS = [
    # Launcher icon and its alternative (Settings, System, alternative app icon)
    ("utubot-symbol.svg", FLAVOR_RES / "app_icon.png", 320, 320, None),
    ("utubot-symbol-alt.svg", FLAVOR_RES / "app_icon_alt.png", 320, 320, None),
    # Android TV launcher banner
    ("utubot-banner.svg", FLAVOR_RES / "app_banner.png", 640, 360, None),
    # Logo of the browse screen header: default, monochrome scheme, red scheme (kept in the brand colors)
    ("utubot-symbol.svg", FLAVOR_RES / "app_logo.png", 180, 180, None),
    ("utubot-symbol.svg", FLAVOR_RES / "app_logo_semi_red.png", 180, 180, None),
    ("utubot-symbol-mono.svg", FLAVOR_RES / "app_logo_semi_grey.png", 180, 180, None),
    # Previews for the README and pull requests
    ("utubot-symbol.svg", PREVIEW_DIR / "utubot-symbol.png", 512, 512, None),
    ("utubot-symbol-alt.svg", PREVIEW_DIR / "utubot-symbol-alt.png", 512, 512, None),
    ("utubot-symbol-mono.svg", PREVIEW_DIR / "utubot-symbol-mono.png", 512, 512, None),
    ("utubot-banner.svg", PREVIEW_DIR / "utubot-banner.png", 1280, 720, None),
    ("utubot-wordmark.svg", PREVIEW_DIR / "utubot-wordmark.png", 1408, 464, INK),
]


def body(svg_name: str) -> list[str]:
    """The drawing lines of an SVG file: everything after its title, without the closing tag."""
    text = (BRAND_DIR / svg_name).read_text(encoding="utf-8")
    inner = re.search(r"</title>\n(.*)</svg>", text, re.S).group(1)
    return [line.strip() for line in inner.splitlines() if line.strip()]


def check_banner_in_sync() -> None:
    banner = [line.strip() for line in (BRAND_DIR / BANNER).read_text(encoding="utf-8").splitlines()]

    for source in (SYMBOL, WORDMARK):
        missing = [line for line in body(source) if line not in banner]

        if missing:
            sys.exit(f"{BANNER} is out of sync with {source}: copy these lines into it\n" + "\n".join(missing))


def main() -> None:
    check_banner_in_sync()

    for source, destination, width, height, background in TARGETS:
        destination.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(
            url=str(BRAND_DIR / source),
            write_to=str(destination),
            output_width=width,
            output_height=height,
            background_color=background,
        )
        print(f"{destination.relative_to(REPO_ROOT)}  {width}x{height}")


if __name__ == "__main__":
    main()
