#!/usr/bin/env python3
"""A stand-in for the Stremio catalogue and stream addon of the films screens, for emulator checks (no real service is contacted).

Serves, on one port: /catalog/{type}/{id}.json, /catalog/{type}/top/search={text}.json, /meta/{type}/{id}.json,
/stream/{type}/{id}.json (a mix of formats, including Dolby Vision profile 5), /img/{name}.png (generated posters and backdrops with PIL)
and /media/film.mp4 (the file given with --media, the address every stream points to).

    python3 scripts/emulator_mock_films.py --port 18791 --media temp/film.mp4 &
    # prefs of the app: films_developer=true, films_catalog_url=http://10.0.2.2:18791, films_addon_url=http://10.0.2.2:18791
"""
import argparse
import io
import json
import os
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageDraw

MOVIES = [
    ("tt0000001", "The Long Voyage", "2021", "8.1", "148 min", "A ship's cartographer sails past the edge of every map she has drawn."),
    ("tt0000002", "Night Harbour", "2019", "7.4", "112 min", "Two brothers share one last night shift at a harbour that is about to close."),
    ("tt0000003", "Paper Moons", "2023", "7.9", "126 min", "A travelling cinema crosses a desert, one reel short of a finale."),
    ("tt0000004", "Glass Orchard", "2018", "6.8", "98 min", "An orchard keeper hears the trees whisper the price of her land."),
    ("tt0000005", "Low Tide", "2022", "7.2", "104 min", "A diver returns to the wreck she swore she would never open."),
    ("tt0000006", "Iron Lantern", "2020", "8.4", "139 min", "A lighthouse is the last signal in a war that nobody remembers."),
    ("tt0000007", "Quiet Engines", "2024", "7.6", "117 min", "The last train of the year carries a secret and one stowaway."),
    ("tt0000008", "Salt and Smoke", "2017", "7.0", "101 min", "A chef cooks the meal that will decide who inherits the island."),
]
SERIES = [
    ("tt1000001", "Harbour Lights", "2020", "8.6", "45 min", "A small port town and the people who keep its lights on."),
    ("tt1000002", "The Cartel Files", "2022", "8.0", "52 min", "Reporters follow one shipment through five countries."),
    ("tt1000003", "Deep Field", "2023", "7.7", "48 min", "An observatory crew finds a signal that repeats."),
    ("tt1000004", "Moss and Stone", "2019", "7.3", "40 min", "A family inherits a ruined abbey and its debts."),
]
STREAMS = [
    ("Torrentio\n4k DV | HDR", "Movie.2160p.UHD.BluRay.REMUX.HEVC.DV.P5.TrueHD.Atmos-GRP", 58 * 1024 ** 3),
    ("Torrentio\n4k HDR", "Movie.2160p.WEB-DL.DDP5.1.HDR10.HEVC.10bit-GRP", 18 * 1024 ** 3),
    ("Torrentio\n4k DV", "Movie.2160p.WEB-DL.DoVi.Profile.8.HDR10.DDP5.1.Atmos.HEVC-GRP", 22 * 1024 ** 3),
    ("Torrentio\n1080p", "Movie.1080p.BluRay.x264.DTS-HD.5.1-GRP", 11 * 1024 ** 3),
    ("Torrentio\n1080p", "Movie.1080p.WEB-DL.AAC2.0.x264-GRP", 4 * 1024 ** 3),
    ("Torrentio\n720p", "Movie.720p.HDTV.x264.AC3-GRP", 2 * 1024 ** 3),
]
COLOURS = [(47, 111, 176), (176, 80, 47), (60, 140, 90), (140, 60, 150), (180, 150, 40), (40, 130, 150), (150, 50, 70), (90, 90, 160)]


def entries(kind):
    return MOVIES if kind == "movie" else SERIES


def meta_of(kind, row, port, full):
    id_, name, year, rating, runtime, plot = row
    meta = {"id": id_, "type": kind, "name": name, "releaseInfo": year, "imdbRating": rating,
            "poster": f"http://10.0.2.2:{port}/img/p-{id_}.png"}
    if full:
        meta.update({"background": f"http://10.0.2.2:{port}/img/b-{id_}.png", "runtime": runtime, "description": plot})
        if kind == "series":
            meta["videos"] = [{"season": s, "episode": e, "title": f"Episode {e}: {t}"}
                              for s in (1, 2, 3) for e, t in enumerate(["Arrival", "Low Light", "The Sealed Door", "Signal", "Tide Line", "Afterglow"], 1)]
    return meta


def image(name):
    kind, id_ = name[:-4].split("-", 1)
    rows = MOVIES + SERIES
    index = next((i for i, r in enumerate(rows) if r[0] == id_), 0)
    colour = COLOURS[index % len(COLOURS)]
    width, height = (400, 600) if kind == "p" else (1280, 720)
    picture = Image.new("RGB", (width, height), colour)
    draw = ImageDraw.Draw(picture)
    for y in range(height):
        shade = int(120 * y / height)
        draw.line([(0, y), (width, y)], fill=(max(colour[0] - shade, 0), max(colour[1] - shade, 0), max(colour[2] - shade, 0)))
    draw.ellipse([width * 0.2, height * 0.15, width * 0.8, height * 0.55], outline=(255, 255, 255), width=6)
    draw.text((width * 0.08, height * 0.8), rows[index][1], fill=(255, 255, 255))
    out = io.BytesIO()
    picture.save(out, "PNG")
    return out.getvalue()


class Handler(BaseHTTPRequestHandler):
    media = None

    def log_message(self, *args):
        pass

    def send(self, body, kind="application/json", code=200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        port = self.server.server_address[1]
        path = urllib.parse.unquote(self.path.split("?")[0])
        parts = path.strip("/").split("/")
        if parts[0] == "img" and len(parts) == 2:
            return self.send(image(parts[1]), "image/png")
        if parts[0] == "media" and self.media and os.path.exists(self.media):
            with open(self.media, "rb") as handle:
                return self.send(handle.read(), "video/mp4")
        if parts[0] == "catalog" and len(parts) >= 3:
            kind, rest = parts[1], "/".join(parts[2:])
            rows = entries(kind)
            if "search=" in rest:
                text = rest.split("search=")[1].removesuffix(".json").lower()
                rows = [r for r in rows if text in r[1].lower()]
            elif rest.startswith("year"):
                rows = list(reversed(rows))
            return self.send(json.dumps({"metas": [meta_of(kind, r, port, False) for r in rows]}).encode())
        if parts[0] == "meta" and len(parts) == 3:
            kind, id_ = parts[1], parts[2].removesuffix(".json")
            row = next((r for r in entries(kind) if r[0] == id_), None)
            return self.send(json.dumps({"meta": meta_of(kind, row, port, True)}).encode()) if row else self.send(b"{}", code=404)
        if parts[0] == "stream":
            streams = [{"name": name, "title": title + "\n\U0001F464 12 \U0001F4BE " + str(size >> 30) + " GB",
                        "url": f"http://10.0.2.2:{port}/media/film.mp4?s={i}", "behaviorHints": {"videoSize": size}}
                       for i, (name, title, size) in enumerate(STREAMS)]
            return self.send(json.dumps({"streams": streams}).encode())
        self.send(b"{}", code=404)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18791)
    parser.add_argument("--media")
    args = parser.parse_args()
    Handler.media = args.media
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
