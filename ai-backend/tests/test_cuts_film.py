"""Cuts of a film: the film source on the cut API, built from the subtitles of its release."""

from __future__ import annotations

import httpx
import pytest

from tests.test_cuts_api import wait_ready
from tests.test_films import cues, public, srt
from utubot.config import LLMTask
from utubot.films import FilmSubtitles, film_video_id

KEY = "imdb:tt0111161"
RELEASE = "The.Movie.1994.1080p.BluRay.x264-GROUP.mkv|4000000"
FID = film_video_id(KEY, RELEASE)
DURATION_MS = 600_000
POSTER = "https://images.metahub.space/poster/small/tt0111161/img"
ANSWER = {"parts": [{"from": 1, "to": 30, "label": "The first half"}], "summary": "s", "kept_s": 300}


def film_params(release=RELEASE, key=KEY, duration_ms=DURATION_MS, **extra):
    return {
        "source_kind": "film",
        "source_key": key,
        "release_key": release,
        "release_duration_ms": duration_ms,
        "title": "The Movie",
        "poster": POSTER,
        "file_name": release.split("|")[0],
        **extra,
    }


class Addon:
    """The subtitles add-on: a list of candidates and the files they point to."""

    def __init__(self):
        self.requests: list[str] = []
        self.items = [
            {"id": "1", "url": "http://subs.test/a.srt", "lang": "eng", "subtitleFileName": "x.srt"}
        ]
        self.files = {"/a.srt": srt([(s, e, t + ".") for s, e, t in cues(58)])}

    def transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            if request.url.path.startswith("/subtitles/"):
                return httpx.Response(200, json={"subtitles": self.items})
            body = self.files.get(request.url.path)
            return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

        return httpx.MockTransport(handler)


@pytest.fixture
async def film_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.addon = Addon()
    env.svc.cuts.films = FilmSubtitles(env.cfg.films, env.addon.transport(), public)
    env.cfg.films.subtitles_url = "http://addon.test"
    env.llm.cut_answer = ANSWER
    return env


async def post_film(env, video_id=FID, params=None, **body):
    return await env.client.post(
        f"/v1/videos/{video_id}/cuts", params=params or film_params(), json=body
    )


class TestFilmCut:
    async def test_a_film_cut_builds_from_the_subtitles_of_its_release(self, film_env):
        r = await post_film(film_env, preset="cut-highlights-5")
        assert r.status_code == 200, r.text
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        cut = doc["cut"]
        assert cut["video_id"] == FID
        assert cut["duration_ms"] == DURATION_MS
        assert cut["source"] == {
            "kind": "film",
            "key": KEY,
            "release_key": RELEASE,
            "release_duration_ms": DURATION_MS,
        }
        assert cut["skip_ranges_ms"] and cut["skip_ranges_ms"][-1][1] == DURATION_MS
        # the request and the stored cut carry the source columns
        row = film_env.svc.db.one("SELECT * FROM cut_requests WHERE id=?", [doc["id"]])
        assert (row["source_kind"], row["source_key"], row["release_key"]) == ("film", KEY, RELEASE)
        assert row["release_duration_ms"] == DURATION_MS
        stored = film_env.svc.db.one("SELECT * FROM cuts WHERE video_id=?", [FID])
        assert (stored["source_kind"], stored["source_key"], stored["release_key"]) == (
            "film",
            KEY,
            RELEASE,
        )

    async def test_only_the_id_and_the_file_name_reach_the_subtitles_service(self, film_env):
        r = await post_film(film_env, preset="cut-highlights-5")
        await wait_ready(film_env, r.json()["request_id"])
        asked = film_env.addon.requests[0]
        assert "/subtitles/movie/tt0111161/" in asked
        assert "filename=The.Movie.1994.1080p.BluRay.x264-GROUP.mkv" in asked
        for private in ("token", "user", "utubot", POSTER, "The%20Movie"):
            assert private not in asked

    async def test_the_subtitles_are_fetched_once_per_release(self, film_env):
        first = await post_film(film_env, preset="cut-highlights-5")
        await wait_ready(film_env, first.json()["request_id"])
        second = await post_film(film_env, preset="cut-skim-film")
        doc = await wait_ready(film_env, second.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        assert len([u for u in film_env.addon.requests if "/subtitles/" in u]) == 1

    async def test_the_queue_card_shows_the_film_title_and_poster(self, film_env):
        r = await post_film(film_env, preset="cut-highlights-5")
        cards = (await film_env.client.get("/v1/cut-requests")).json()["requests"]
        card = next(c for c in cards if c["id"] == r.json()["request_id"])
        assert card["title"] == "The Movie"
        assert card["thumbnail"] == POSTER and card["source_kind"] == "film"

    async def test_a_poster_from_another_origin_is_not_stored_and_the_page_may_show_the_configured_one(
        self, film_env
    ):
        film_env.cfg.films.poster_origins = ["https://images.example"]
        params = film_params(poster="https://tracker.example/p.jpg")
        r = await post_film(film_env, params=params, preset="cut-highlights-5")
        cards = (await film_env.client.get("/v1/cut-requests")).json()["requests"]
        assert "thumbnail" not in next(c for c in cards if c["id"] == r.json()["request_id"])
        params = film_params(poster="https://images.example/p.jpg")
        r = await post_film(film_env, params=params, preset="cut-skim-film")
        cards = (await film_env.client.get("/v1/cut-requests")).json()["requests"]
        assert next(c for c in cards if c["id"] == r.json()["request_id"])["thumbnail"].startswith(
            "https://images.example/"
        )

    async def test_the_skim_preset_targets_the_release_length(self, film_env):
        film_env.llm.cut_answer = {
            "parts": [{"from": i, "to": i, "label": f"P{i}", "rank": 60 - i} for i in range(1, 59)],
            "summary": "skim",
        }
        r = await post_film(film_env, preset="cut-skim-film")
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        assert doc["cut"]["target_s"] == DURATION_MS // 2000

    async def test_a_cut_of_a_film_never_asks_youtube(self, film_env):
        r = await post_film(film_env, preset="cut-highlights-5")
        await wait_ready(film_env, r.json()["request_id"])
        assert film_env.fetcher.calls == [] and film_env.fetcher.meta_calls == []


class TestFilmPresets:
    async def test_a_film_lists_only_presets_that_fit_a_film(self, film_env):
        state = (await film_env.client.get(f"/v1/videos/{FID}/cuts", params=film_params())).json()
        ids = [p["id"] for p in state["presets"]]
        assert "cut-skim-film" in ids and "cut-highlights-5" in ids
        assert not {"cut-answer", "cut-demo", "cut-no-filler"} & set(ids)

    async def test_a_youtube_video_keeps_every_preset(self, film_env):
        state = (await film_env.client.get("/v1/videos/abcdefghijk/cuts")).json()
        ids = [p["id"] for p in state["presets"]]
        assert {"cut-answer", "cut-demo", "cut-no-filler", "cut-skim-film"} <= set(ids)

    async def test_a_hidden_preset_is_refused_for_a_film(self, film_env):
        r = await post_film(film_env, preset="cut-demo")
        assert r.status_code == 409

    async def test_force_is_ignored_for_a_film(self, film_env):
        r = await post_film(film_env, preset="cut-skim-film", force=True)
        row = film_env.svc.db.one(
            "SELECT force, refetch FROM cut_requests WHERE id=?", [r.json()["request_id"]]
        )
        assert (row["force"], row["refetch"]) == (0, 0)


class TestFilmRefusals:
    async def test_an_id_that_is_not_the_release_s_is_refused(self, film_env):
        r = await post_film(film_env, video_id="abcdefghijk", preset="cut-highlights-5")
        assert r.status_code == 400

    async def test_a_bad_source_key_is_refused(self, film_env):
        r = await post_film(film_env, params=film_params(key="imdb:nope"), preset="cut-highlights-5")
        assert r.status_code == 400

    async def test_watched_is_not_offered_and_not_accepted(self, film_env):
        state = (await film_env.client.get(f"/v1/videos/{FID}/cuts", params=film_params())).json()
        watched = next(m for m in state["modes"] if m["id"] == "watched")
        assert watched["available"] is False and "subtitles" in watched["reason"]
        assert state["default_mode"] == "quick"
        r = await post_film(film_env, preset="cut-highlights-5", mode="watched")
        assert r.status_code == 409

    async def test_subtitles_that_do_not_fit_fail_the_cut_in_plain_words(self, film_env):
        film_env.addon.files["/a.srt"] = srt(cues(70))
        r = await post_film(film_env, preset="cut-highlights-5")
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "subtitles run to" in doc["error"]

    async def test_no_subtitles_fail_the_cut_in_plain_words(self, film_env):
        film_env.addon.items = []
        r = await post_film(film_env, preset="cut-highlights-5")
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "No subtitles were found" in doc["error"]

    async def test_a_film_with_no_known_length_asks_to_play_it_first(self, film_env):
        params = film_params()
        del params["release_duration_ms"]
        r = await post_film(film_env, params=params, preset="cut-highlights-5")
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "Play the film" in doc["error"]


class TestEmbeddedTracks:
    async def test_captions_the_tv_sent_from_the_file_are_used_without_the_service(self, film_env):
        film_env.addon.items = []
        film_env.addon.files = {}
        vtt = "WEBVTT\n\n" + "\n\n".join(
            f"00:{(5 + i * 10) // 60:02d}:{(5 + i * 10) % 60:02d}.000 --> "
            f"00:{(10 + i * 10) // 60:02d}:{(10 + i * 10) % 60:02d}.000\nEmbedded line {i}."
            for i in range(58)
        )
        await film_env.client.get(f"/v1/videos/{FID}/cuts", params=film_params())
        up = await film_env.client.post(
            f"/v1/videos/{FID}/captions/client",
            json={"tracks": [{"lang": "en", "kind": "manual", "format": "vtt", "body": vtt}]},
        )
        assert up.status_code == 200, up.text
        r = await post_film(film_env, preset="cut-highlights-5")
        doc = await wait_ready(film_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        assert film_env.addon.requests == []


class TestReleases:
    async def test_a_cut_of_another_release_is_offered_only_when_its_length_agrees(self, film_env):
        first = await post_film(film_env, preset="cut-highlights-5")
        done = await wait_ready(film_env, first.json()["request_id"])
        assert done["state"] == "ready"

        other = "Other.Release.720p.mkv|900"
        near = film_params(release=other, duration_ms=DURATION_MS + 1500)
        state = (
            await film_env.client.get(f"/v1/videos/{film_video_id(KEY, other)}/cuts", params=near)
        ).json()
        demo = next(p for p in state["presets"] if p["id"] == "cut-highlights-5")
        assert demo["state"] == "ready"
        assert demo["cut"]["video_id"] == film_video_id(KEY, other)
        assert demo["cut"]["skip_ranges_ms"] == done["cut"]["skip_ranges_ms"]

        far = film_params(release=other, duration_ms=DURATION_MS + 60_000)
        state = (
            await film_env.client.get(f"/v1/videos/{film_video_id(KEY, other)}/cuts", params=far)
        ).json()
        assert next(p for p in state["presets"] if p["id"] == "cut-highlights-5")["state"] == "none"

    async def test_another_title_never_shares_a_cut(self, film_env):
        first = await post_film(film_env, preset="cut-highlights-5")
        await wait_ready(film_env, first.json()["request_id"])
        key = "imdb:tt0000002"
        params = film_params(key=key, release="Other.mkv|1")
        state = (
            await film_env.client.get(
                f"/v1/videos/{film_video_id(key, 'Other.mkv|1')}/cuts", params=params
            )
        ).json()
        assert next(p for p in state["presets"] if p["id"] == "cut-highlights-5")["state"] == "none"

    async def test_an_episode_asks_the_service_by_season_and_episode(self, film_env):
        key, release = "imdb:tt0944947:S2E5", "Show.S02E05.mkv|1"
        params = film_params(key=key, release=release)
        r = await post_film(
            film_env, video_id=film_video_id(key, release), params=params, preset="cut-highlights-5"
        )
        await wait_ready(film_env, r.json()["request_id"])
        assert "/subtitles/series/tt0944947:2:5/" in film_env.addon.requests[0]


async def test_the_page_may_show_images_from_the_poster_origins(film_env):
    r = await film_env.client.get("/")
    csp = r.headers["content-security-policy"]
    assert "img-src 'self' data: https://i.ytimg.com https://images.metahub.space;" in csp
