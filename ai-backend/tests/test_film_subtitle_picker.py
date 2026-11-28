"""The TV's subtitle picker: the list of subtitles for a stream and one of them as WebVTT."""

from __future__ import annotations

import httpx
import pytest

from tests.test_films import cues, public, srt
from utubot.films import (
    FilmSubtitles,
    TtlCache,
    list_subtitles,
    subtitle_id,
    vtt_time,
    webvtt,
)

KEY = "imdb:tt0111161"
FILE = "The.Movie.1994.1080p.BluRay.x264-GROUP.mkv"
ITEMS = [
    {
        "id": "en-weak",
        "url": "http://subs.test/1.srt",
        "lang": "eng",
        "subtitleFileName": "Movie.720p.WEB.srt",
    },
    {
        "id": "en-best",
        "url": "http://subs.test/2.srt",
        "lang": "eng",
        "subtitleFileName": "The.Movie.1994.1080p.BluRay.x264-GROUP.srt",
        "releaseGroup": "GROUP",
    },
    {
        "id": "tr-1",
        "url": "http://subs.test/3.srt",
        "lang": "tur",
        "subtitleFileName": "Movie.1080p.srt",
    },
    {
        "id": "fr-1",
        "url": "http://subs.test/4.srt",
        "lang": "fre",
        "subtitleFileName": "Movie.fr.srt",
    },
    {"id": "no-url", "lang": "eng", "subtitleFileName": "x.srt"},
    {"id": "other-ep", "url": "http://subs.test/5.srt", "lang": "eng", "season": 2, "episode": 1},
]


class TestListing:
    def test_the_viewers_language_then_english_each_best_match_first(self):
        listed = list_subtitles(ITEMS, FILE, "tr")

        assert [s["id"] for s in listed] == ["tr-1", "en-best", "en-weak", "other-ep"]
        assert listed[0]["best"] is True and "best" not in listed[1]

    def test_without_a_language_it_is_english(self):
        assert [s["id"] for s in list_subtitles(ITEMS, FILE, None)] == [
            "en-best",
            "en-weak",
            "other-ep",
        ]

    def test_an_episode_drops_other_episodes_and_files_without_an_address(self):
        listed = list_subtitles(ITEMS, FILE, "en", season=1, episode=3)

        assert "other-ep" not in [s["id"] for s in listed]
        assert "no-url" not in [s["id"] for s in listed]

    def test_the_release_match_ranks_within_a_language(self):
        listed = list_subtitles(ITEMS, FILE, "en")
        scores = {s["id"]: s["score"] for s in listed}

        assert scores["en-best"] > scores["en-weak"]

    def test_ids_are_safe_for_a_path_and_never_empty(self):
        assert subtitle_id({"id": "a/b?c d", "url": "x"}) == "abcd"
        assert len(subtitle_id({"url": "http://x/y"})) == 16


class TestWebvtt:
    def test_cues_become_a_vtt_file(self):
        text = webvtt([(1.5, 3.25, "Hello"), (3661.0, 3662.0, "A --> B")])

        assert text.startswith("WEBVTT\n\n00:00:01.500 --> 00:00:03.250\nHello\n")
        assert "01:01:01.000 --> 01:01:02.000\nA -> B" in text

    def test_time_format(self):
        assert vtt_time(0) == "00:00:00.000"
        assert vtt_time(59.9996) == "00:01:00.000"


class TestCache:
    def test_entries_expire_and_the_oldest_go(self):
        now = [0.0]
        cache = TtlCache(entries=2, ttl_s=10, clock=lambda: now[0])
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        assert cache.get("a") is None and cache.get("c") == 3
        now[0] = 11
        assert cache.get("c") is None


class Addon:
    def __init__(self):
        self.requests: list[str] = []
        self.files = {"/2.srt": srt([(s, e, t + ".") for s, e, t in cues(5)])}

    def transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            if request.url.path.startswith("/subtitles/"):
                return httpx.Response(200, json={"subtitles": ITEMS})
            body = self.files.get(request.url.path)
            return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

        return httpx.MockTransport(handler)


@pytest.fixture
def picker_env(env):
    env.addon = Addon()
    env.svc.cuts.films = FilmSubtitles(env.cfg.films, env.addon.transport(), public)
    env.cfg.films.subtitles_url = "http://addon.test"
    env.cfg.films.download_hosts = ["subs.test"]
    return env


PARAMS = {"source_key": KEY, "file_name": FILE, "size": 123456}


async def test_the_list_route_answers_the_picker(picker_env):
    r = await picker_env.client.get("/v1/films/subtitles", params={**PARAMS, "lang": "tr"})

    assert r.status_code == 200, r.text
    ids = [s["id"] for s in r.json()["subtitles"]]
    assert ids[:3] == ["tr-1", "en-best", "en-weak"]
    assert (
        "filename=" in picker_env.addon.requests[0]
        and "videoSize=123456" in picker_env.addon.requests[0]
    )


async def test_the_file_route_gives_webvtt_and_asks_the_addon_once(picker_env):
    first = await picker_env.client.get("/v1/films/subtitles/en-best.vtt", params=PARAMS)
    second = await picker_env.client.get("/v1/films/subtitles/en-best.vtt", params=PARAMS)

    assert first.status_code == 200 and first.headers["content-type"].startswith("text/vtt")
    assert first.text.startswith("WEBVTT") and "Line 0." in first.text
    assert second.text == first.text
    assert len([u for u in picker_env.addon.requests if u.endswith("/2.srt")]) == 1
    assert len([u for u in picker_env.addon.requests if "/subtitles/" in u]) == 1


async def test_an_unknown_subtitle_or_a_bad_key_is_refused(picker_env):
    unknown = await picker_env.client.get("/v1/films/subtitles/nope.vtt", params=PARAMS)
    assert unknown.status_code == 404

    bad = await picker_env.client.get(
        "/v1/films/subtitles", params={**PARAMS, "source_key": "tt0111161"}
    )
    assert bad.status_code == 400


async def test_the_routes_need_a_signed_in_user(picker_env):
    from tests.test_voice_api import anon_client

    anon = anon_client(picker_env)
    assert (await anon.get("/v1/films/subtitles", params=PARAMS)).status_code == 401
    assert (await anon.get("/v1/films/subtitles/en-best.vtt", params=PARAMS)).status_code == 401


async def test_a_service_failure_is_a_502(picker_env):
    picker_env.svc.cuts.films = FilmSubtitles(
        picker_env.cfg.films, httpx.MockTransport(lambda r: httpx.Response(500)), public
    )
    r = await picker_env.client.get("/v1/films/subtitles", params=PARAMS)

    assert r.status_code == 502 and "error" in r.json()
