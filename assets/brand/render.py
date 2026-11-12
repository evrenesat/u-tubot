# /// script
# requires-python = ">=3.10"
# dependencies = ["cairosvg==2.9.1"]
# ///
"""Renders the SVG sources in this directory to the PNGs of the stutubot flavor and to previews.

Run from anywhere: `uv run assets/brand/render.py` (needs the cairo system library, e.g. `apt install libcairo2`).
The SVGs carry no fonts (the wordmark is drawn with paths), so the output does not depend on the machine.
The banner repeats the markup of the symbol and the wordmark (one file, no external references): the script stops when they differ.
The Settings tile icon (`settings_utubot.png`, white on transparent like the other Settings icons) is cut from the monochrome symbol:
the tile is dropped, the white shapes and the light dot stay, the grey ones (the u, the ring around the dot) become holes. It is fitted
into the canvas and padding of `settings_about.png`, measured from that file.
"""
import io
import re
import sys
from pathlib import Path

import cairosvg
from PIL import Image, ImageChops

BRAND_DIR = Path(__file__).resolve().parent
REPO_ROOT = BRAND_DIR.parent.parent
FLAVOR_RES = REPO_ROOT / "smarttubetv" / "src" / "stutubot" / "res" / "mipmap-nodpi"
PREVIEW_DIR = BRAND_DIR / "png"
SETTINGS_ICONS = REPO_ROOT / "common" / "src" / "main" / "res" / "drawable-nodpi"
SETTINGS_ICON = SETTINGS_ICONS / "settings_utubot.png"
SETTINGS_ICON_REFERENCE = SETTINGS_ICONS / "settings_about.png"

# (svg, destination, width, height, background): no background is transparent
INK = "#0F1124"
SYMBOL = "utubot-symbol.svg"
WORDMARK = "utubot-wordmark.svg"
BANNER = "utubot-banner.svg"
MONO_SYMBOL = "utubot-symbol-mono.svg"
# The colors of the monochrome symbol: the grey of the tile, the u and the ring is cut out, the light dot stays
MONO_CUT = (0x6B, 0x70, 0x80)
MONO_ACCENT = (0xB9, 0xBD, 0xC9)
TILE_SHAPE = re.compile(r"<rect\b[^>]*/>\s*")
VIEW_BOX = re.compile(r'viewBox="[^"]*"')
# The icon is measured at this scale before it is fitted, for a clean edge of the shapes
MEASURE_SCALE = 4
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


def luma(color: tuple[int, int, int]) -> float:
    red, green, blue = color

    return 0.299 * red + 0.587 * green + 0.114 * blue


def ink_alpha(svg: str, size: int) -> Image.Image:
    """The part of the monochrome symbol that is not grey, as an alpha mask: grey (the cut) is 0, the light dot and white are 1.

    Edges between two colors blend linearly in the render, so the luminance between the grey and the light dot is the coverage."""
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=size, output_height=size)
    rendered = Image.open(io.BytesIO(png)).convert("RGBA")
    low, high = luma(MONO_CUT), luma(MONO_ACCENT)
    coverage = rendered.convert("L").point(lambda value: round(255 * min(1.0, max(0.0, (value - low) / (high - low)))))

    return ImageChops.multiply(rendered.getchannel("A"), coverage)


def settings_icon_canvas() -> tuple[int, int]:
    """The size and the padding of the reference Settings icon: the gap between its shape and the edge of its canvas."""
    reference = Image.open(SETTINGS_ICON_REFERENCE).convert("RGBA")
    left, top, right, bottom = reference.getchannel("A").getbbox()
    width, height = reference.size

    return width, min(left, top, width - right, height - bottom)


def render_settings_icon() -> None:
    """Renders `settings_utubot.png`: the monochrome symbol without its tile, white on transparent, fitted into the reference canvas."""
    source = (BRAND_DIR / MONO_SYMBOL).read_text(encoding="utf-8")
    symbol, tiles = TILE_SHAPE.subn("", source)

    if tiles != 1:
        sys.exit(f"{MONO_SYMBOL} should have exactly one tile (a rect), found {tiles}")

    for color in (MONO_CUT, MONO_ACCENT):
        if "#%02X%02X%02X" % color not in symbol:
            sys.exit(f"{MONO_SYMBOL} no longer uses #%02X%02X%02X: update MONO_CUT and MONO_ACCENT" % color)

    size, padding = settings_icon_canvas()
    view_box = [float(value) for value in VIEW_BOX.search(symbol).group(0).split('"')[1].split()]
    source_size = view_box[2]
    measure = size * MEASURE_SCALE
    left, top, right, bottom = ink_alpha(symbol, measure).getbbox()
    unit = source_size / measure
    center_x, center_y = (left + right) / 2 * unit, (top + bottom) / 2 * unit
    # The longer side of the shapes spans the canvas minus the padding on both sides
    side = max(right - left, bottom - top) * unit * size / (size - 2 * padding)
    fitted = VIEW_BOX.sub(f'viewBox="{center_x - side / 2:.4f} {center_y - side / 2:.4f} {side:.4f} {side:.4f}"', symbol)

    icon = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    icon.putalpha(ink_alpha(fitted, size))
    SETTINGS_ICON.parent.mkdir(parents=True, exist_ok=True)
    icon.save(SETTINGS_ICON, optimize=True)
    print(f"{SETTINGS_ICON.relative_to(REPO_ROOT)}  {size}x{size}  padding {padding}")


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

    render_settings_icon()


if __name__ == "__main__":
    main()
