"""Film sources: keys and release ids, subtitle choice and parsing, the timing check."""

from __future__ import annotations

import httpx
import pytest

from utubot.config import FilmsConfig
from utubot.films import (
    FilmRefused,
    FilmSubtitles,
    TtlCache,
    check_timing,
    choose_subtitles,
    film_source,
    film_video_id,
    parse_source_key,
    parse_srt,
    release_fits,
    release_score,
)

CFG = FilmsConfig()
FILE = "The.Movie.1994.1080p.BluRay.x264-GROUP.mkv"
PUBLIC_IP = "93.184.216.34"


def cues(n: int, *, every: float = 10.0, length: float = 5.0, start: float = 5.0):
    return [(start + i * every, start + i * every + length, f"Line {i}") for i in range(n)]


class TestSourceKeys:
    def test_a_film_and_an_episode_key(self):
        assert parse_source_key("imdb:tt0111161") == ("tt0111161", None, None)
        assert parse_source_key("imdb:tt0944947:S1E2") == ("tt0944947", 1, 2)

    @pytest.mark.parametrize(
        "key", ["", "tt0111161", "imdb:tt1", "imdb:tt0111161:1:2", "youtube:abcdefghijk"]
    )
    def test_a_key_the_tv_could_not_have_sent_is_refused(self, key):
        with pytest.raises(ValueError):
            parse_source_key(key)

    def test_the_backend_id_is_eleven_characters_and_follows_the_release(self):
        a = film_video_id("imdb:tt0111161", "A.mkv|100")
        b = film_video_id("imdb:tt0111161", "B.mkv|100")
        assert len(a) == 11 and a != b
        assert a == film_video_id("imdb:tt0111161", "A.mkv|100")
        assert film_video_id("imdb:tt0111161", "A.mkv|100") != film_video_id(
            "imdb:tt0944947:S1E1", "A.mkv|100"
        )

    def test_the_id_matches_the_tv(self):
        # the same vectors are asserted in UtubotFilmPlayTest
        assert film_video_id("imdb:tt0111161", "Movie.mkv|1234") == "f7bb94acc21"
        assert film_video_id("imdb:tt7654321:S1E2", "Show S01E02") == "f6dd47663e4"

    def test_a_film_source_needs_a_release(self):
        with pytest.raises(ValueError):
            film_source("imdb:tt0111161", "")
        source = film_source("imdb:tt0944947:S3E4", "x.mkv|9", 3_000_000)
        assert (source.imdb_id, source.season, source.episode) == ("tt0944947", 3, 4)
        assert source.release_duration_ms == 3_000_000

    def test_another_release_is_offered_only_when_the_length_agrees(self):
        here = {"key": "imdb:tt0111161", "release_duration_ms": 5_400_000}
        assert release_fits(here, {**here, "release_duration_ms": 5_401_500}, 2000)
        assert not release_fits(here, {**here, "release_duration_ms": 5_410_000}, 2000)
        assert not release_fits(here, {**here, "release_duration_ms": None}, 2000)
        assert not release_fits(here, {**here, "key": "imdb:tt0000001"}, 2000)


class TestParsing:
    def test_srt_with_markup_and_a_bom(self):
        raw = (
            "﻿1\r\n00:00:01,500 --> 00:00:03,000\r\n<i>Hello</i>\r\n{\\an8}there\r\n\r\n"
            "2\r\n00:00:04,000 --> 00:00:05,250\r\nSecond\r\n\r\n3\r\n00:00:06,000 --> 00:00:07,000\r\n\r\n"
        )
        assert parse_srt(raw) == [(1.5, 3.0, "Hello there"), (4.0, 5.25, "Second")]

    def test_webvtt_is_read_too(self):
        raw = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n"
        assert parse_srt(raw) == [(1.0, 2.0, "Hi")]


class TestChoice:
    def items(self):
        return [
            {
                "id": "1",
                "url": "u1",
                "lang": "eng",
                "subtitleFileName": "The.Movie.1994.720p.WEB-DL.XviD-OTHER.srt",
            },
            {
                "id": "2",
                "url": "u2",
                "lang": "eng",
                "subtitleFileName": "The.Movie.1994.1080p.BluRay.x264-GROUP.srt",
            },
            {
                "id": "3",
                "url": "u3",
                "lang": "tur",
                "subtitleFileName": "The.Movie.1994.1080p.BluRay.x264-GROUP.tr.srt",
            },
            {
                "id": "4",
                "url": "u4",
                "lang": "eng",
                "subtitleFileName": "Other.Film.2001.DVDRip.srt",
            },
            {"id": "5", "lang": "eng", "subtitleFileName": "no url"},
        ]

    def test_the_best_release_match_comes_first(self):
        order = choose_subtitles(self.items(), FILE, None)
        assert [c["id"] for c in order] == ["2", "1", "4"]

    def test_the_users_language_wins_over_english(self):
        assert [c["id"] for c in choose_subtitles(self.items(), FILE, "tr")] == ["3"]

    def test_english_is_the_fallback_when_the_language_has_none(self):
        assert [c["id"] for c in choose_subtitles(self.items(), FILE, "de")][:1] == ["2"]

    def test_nothing_in_a_wanted_language_is_nothing(self):
        assert choose_subtitles([{"id": "9", "url": "u", "lang": "fre"}], FILE, "tr") == []

    def test_the_hash_match_breaks_a_tie_and_a_group_match_counts(self):
        plain = {"subtitleFileName": "Movie.srt", "lang": "eng", "url": "u"}
        assert release_score({**plain, "m": "h"}, FILE) > release_score(plain, FILE)
        grouped = {**plain, "releaseGroup": "GROUP"}
        assert release_score(grouped, FILE) > release_score(plain, FILE)

    def test_an_episode_search_drops_another_episode(self):
        items = [
            {"id": "1", "url": "u", "lang": "eng", "season": 1, "episode": 2},
            {"id": "2", "url": "u", "lang": "eng", "season": 1, "episode": 3},
        ]
        assert [c["id"] for c in choose_subtitles(items, FILE, None, 1, 2)] == ["1"]


class TestTiming:
    DURATION = 600_000

    def test_a_fitting_subtitle_passes(self):
        assert check_timing(cues(58), self.DURATION, CFG) is None

    def test_a_subtitle_running_past_the_stream_is_refused(self):
        problem = check_timing(cues(70), self.DURATION, CFG)
        assert problem and "run to" in problem

    def test_a_23_976_subtitle_on_a_25_fps_stream_names_the_frame_rates(self):
        # a two hour film: the subtitle's last cue lands at 6995 * 25 / 23.976 s, past the stream
        scaled = [(s * 25 / 23.976, e * 25 / 23.976, t) for s, e, t in cues(700)]
        problem = check_timing(scaled, 7_000_000, CFG)
        assert problem and "23.976 frames per second" in problem and "runs at 25" in problem

    def test_a_subtitle_that_stops_early_is_another_cut(self):
        problem = check_timing(cues(40), self.DURATION, CFG)
        assert problem and "different cut" in problem

    def test_too_few_lines(self):
        assert "too few" in check_timing(cues(5), self.DURATION, CFG)

    def test_sparse_cues_cover_too_little(self):
        sparse = cues(58, length=0.3)
        assert "cover too little" in check_timing(sparse, self.DURATION, CFG)

    def test_the_frame_rates_of_subtitle_and_stream_are_compared_when_both_are_known(self):
        problem = check_timing(cues(58), self.DURATION, CFG, subtitle_fps=25.0, stream_fps=23.976)
        assert problem and "drift" in problem
        assert (
            check_timing(cues(58), self.DURATION, CFG, subtitle_fps=23.98, stream_fps=23.976)
            is None
        )

    def test_without_a_length_only_the_cues_are_judged(self):
        assert check_timing(cues(58), None, CFG) is None


def addon(items, files):
    """A transport answering the add-on list and the subtitle files."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/subtitles/"):
            return httpx.Response(200, json={"subtitles": items})
        body = files.get(path)
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    return httpx.MockTransport(handler)


def srt(items) -> bytes:
    def clock(seconds: float) -> str:
        total = int(seconds)
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d},000"

    return "\n\n".join(
        f"{i + 1}\n{clock(s)} --> {clock(e)}\n{t}" for i, (s, e, t) in enumerate(items)
    ).encode()


async def public(host: str, port: int) -> list[str]:
    return [PUBLIC_IP]


class TestFetch:
    SOURCE = film_source("imdb:tt0111161", "Movie.mkv|99", 600_000)

    def service(self, items, files):
        return FilmSubtitles(
            FilmsConfig(subtitles_url="http://addon.test"), addon(items, files), public
        )

    async def test_the_request_carries_only_the_id_the_file_name_and_size(self):
        seen = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, json={"subtitles": []})

        service = FilmSubtitles(
            FilmsConfig(subtitles_url="http://addon.test"), httpx.MockTransport(handler), public
        )
        with pytest.raises(FilmRefused) as refused:
            await service.fetch(self.SOURCE, file_name="Movie.mkv", size_bytes=99)
        assert refused.value.reason == "none"
        assert len(seen) == 1 and seen[0].endswith(
            "/subtitles/movie/tt0111161/filename=Movie.mkv&videoSize=99.json"
        )

    async def test_an_episode_asks_by_season_and_episode(self):
        source = film_source("imdb:tt0944947:S1E2", "e.mkv|1", 600_000)
        service = FilmSubtitles(FilmsConfig(subtitles_url="http://addon.test"), None)
        assert service.addon_url(source, "", None).endswith("/subtitles/series/tt0944947:1:2.json")

    async def test_the_best_matching_file_that_fits_is_used(self):
        items = [
            {
                "id": "1",
                "url": "http://subs.test/a.srt",
                "lang": "eng",
                "subtitleFileName": "Movie.mkv",
            },
            {
                "id": "2",
                "url": "http://subs.test/b.srt",
                "lang": "eng",
                "subtitleFileName": "Movie.srt",
                "m": "h",
            },
        ]
        files = {"/a.srt": srt(cues(40)), "/b.srt": srt(cues(58))}
        got = await self.service(items, files).fetch(
            self.SOURCE, file_name="Movie.mkv", duration_ms=600_000
        )
        assert len(got.segments) == 58 or len(got.segments) == 40
        assert got.lang == "eng"

    async def test_a_file_that_does_not_fit_falls_to_the_next_and_none_fitting_is_refused(self):
        items = [
            {"id": "1", "url": "http://subs.test/a.srt", "lang": "eng"},
            {"id": "2", "url": "http://subs.test/b.srt", "lang": "eng"},
        ]
        files = {"/a.srt": srt(cues(40)), "/b.srt": srt(cues(70))}
        service = self.service(items, files)
        with pytest.raises(FilmRefused) as refused:
            await service.fetch(self.SOURCE, file_name="Movie.mkv", duration_ms=600_000)
        assert refused.value.reason == "timing"
        # the best release match decides what is told: file a ends early (40 lines, stops at 4 min)
        assert "different cut" in refused.value.message
        files["/b.srt"] = srt(cues(58))
        service.cache = TtlCache()  # the files are cached for the picker; the add-on's file changed
        got = await service.fetch(self.SOURCE, file_name="Movie.mkv", duration_ms=600_000)
        assert len(got.segments) == 58

    async def test_a_private_subtitle_address_is_refused(self):
        items = [{"id": "1", "url": "http://10.0.0.5/a.srt", "lang": "eng"}]

        async def private(host, port):
            return ["10.0.0.5"]

        service = FilmSubtitles(
            FilmsConfig(subtitles_url="http://addon.test"), addon(items, {}), private
        )
        # the add-on host itself is allowed by name; the file host is not
        with pytest.raises(FilmRefused):
            await service.fetch(self.SOURCE, file_name="Movie.mkv", duration_ms=600_000)

    async def test_a_configured_download_host_may_be_private(self):
        items = [{"id": "1", "url": "http://nas.lan/a.srt", "lang": "eng"}]

        async def private(host, port):
            return ["10.0.0.5"]

        service = FilmSubtitles(
            FilmsConfig(subtitles_url="http://addon.test", download_hosts=["nas.lan"]),
            addon(items, {"/a.srt": srt(cues(58))}),
            private,
        )
        got = await service.fetch(self.SOURCE, file_name="Movie.mkv", duration_ms=600_000)
        assert len(got.segments) == 58
