"""The Stremio account: log in, read the library, and map it to u·tubot films and episodes."""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from tests.test_films import public
from utubot.config import StremioConfig
from utubot.stremio import (
    StremioClient,
    StremioError,
    map_item,
    map_library,
    parse_episode_id,
    parse_library,
    parse_watched_key,
)

AUTH_URL = "https://stremio.com/api/auth"
DATASTORE_URL = "https://lib.stremio.com/api/datastoreGet"


def cfg() -> StremioConfig:
    return StremioConfig(auth_url=AUTH_URL, datastore_url=DATASTORE_URL)


def b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


class Login:
    """A fake Stremio auth endpoint: a successful answer, or a failure to configure."""

    def __init__(self, status: str = "OK", auth: str = "the-auth-key", error: object = None):
        self.seen: dict | None = None
        self.response = {"status": status, "auth": auth}
        if error is not None:
            self.response["error"] = error

    def transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.seen = json.loads(request.content)
            return httpx.Response(200, json=self.response)

        return httpx.MockTransport(handler)


class Library:
    """A fake Stremio datastore endpoint."""

    def __init__(self, payload: dict):
        self.seen_query: dict | None = None
        self.inner = json.dumps(payload).encode()

    def transport(self):
        def handler(request: httpx.Request) -> httpx.Response:
            self.seen_query = dict(
                pair.split("=", 1) for pair in request.url.query.decode().split("&")
            )
            return httpx.Response(
                200,
                json={"payload": b64url(self.inner.decode()), "signature": "sig"},
            )

        return httpx.MockTransport(handler)


class TestLogin:
    async def test_login_returns_the_auth_key_and_sends_email_and_password(self):
        fake = Login()
        client = StremioClient(cfg(), transport=fake.transport(), resolver=public)
        auth = await client.login("owner@example.com", "p@ss word 2")
        assert auth == "the-auth-key"
        assert fake.seen == {
            "event": "login",
            "payload": {"email": "owner@example.com", "password": "p@ss word 2"},
        }

    async def test_a_login_error_reports_its_message(self):
        fake = Login("Error", None, error={"message": "Wrong email or password."})
        client = StremioClient(cfg(), transport=fake.transport(), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.login("a@b.com", "nope")
        assert exc.value.message == "Wrong email or password."
        assert exc.value.reason == "auth"

    async def test_no_auth_key_is_a_login_failure(self):
        fake = Login("OK", "")
        client = StremioClient(cfg(), transport=fake.transport(), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.login("a@b.com", "x")
        assert exc.value.reason == "auth"

    async def test_unexpected_text_is_a_format_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json at all")

        client = StremioClient(cfg(), transport=httpx.MockTransport(handler), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.login("a@b.com", "x")
        assert exc.value.reason == "format"

    async def test_a_http_failure_is_a_service_error_and_never_quotes_the_key(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="boom")

        client = StremioClient(cfg(), transport=httpx.MockTransport(handler), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.login("a@b.com", "x")
        assert exc.value.reason == "service"
        assert "500" in exc.value.message

    async def test_a_connection_error_is_a_service_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        client = StremioClient(cfg(), transport=httpx.MockTransport(handler), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.login("a@b.com", "x")
        assert exc.value.reason == "service"


class TestLibrary:
    async def test_it_reads_the_library_with_the_auth_key_and_decodes_the_payload(self):
        payload = {"libraryItem": {"tt0111161": {"type": "movie", "name": "Shawshank"}}}
        fake = Library(payload)
        client = StremioClient(cfg(), transport=fake.transport(), resolver=public)
        result = await client.library("the-auth-key")
        assert result == payload
        query = fake.seen_query
        assert query["auth"] == "the-auth-key"
        # The payload is the read of the libraryItem key.
        assert json.loads(base64.urlsafe_b64decode(query["payload"] + "==")) == {
            "op": "read",
            "key": "libraryItem",
        }

    async def test_a_datastore_error_is_a_service_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        client = StremioClient(cfg(), transport=httpx.MockTransport(handler), resolver=public)
        with pytest.raises(StremioError) as exc:
            await client.library("bad-key")
        assert exc.value.reason == "service"


class TestMapping:
    async def test_a_movie_maps_to_its_resume_position(self):
        item = parse_library(
            {
                "libraryItem": {
                    "tt0111161": {"type": "movie", "name": "Shawshank", "timeOffset": 5400}
                }
            }
        )[0]
        mapped = map_item(item)
        assert len(mapped) == 1
        entry = mapped[0]
        assert entry.id == "tt0111161"
        assert entry.type == "movie"
        assert entry.position_ms == 5_400_000
        assert entry.watched is False

    async def test_a_series_maps_every_watched_episode_and_the_resume(self):
        item = parse_library(
            {
                "libraryItem": {
                    "tt0944947": {
                        "type": "series",
                        "name": "Game of Thrones",
                        "timeOffset": 3450,
                        "watched": {"S1E1": 1.0, "S1E2": 0.2, "S1E3": 0.95},
                        "watchedAnyway": {"S1E5": True},
                    }
                }
            }
        )[0]
        mapped = map_item(item)
        ids = {m.id for m in mapped}
        # Every episode in the two maps (S1E2 is below the watched share, so it is not watched) plus
        # the series-level resume entry from timeOffset.
        assert ids == {
            "tt0944947:1:1",
            "tt0944947:1:2",
            "tt0944947:1:3",
            "tt0944947:1:5",
            "tt0944947",
        }
        by_id = {m.id: m for m in mapped}
        assert by_id["tt0944947:1:1"].watched is True
        assert by_id["tt0944947:1:2"].watched is False
        assert by_id["tt0944947:1:5"].watched is True  # watchedAnyway
        assert by_id["tt0944947"].position_ms == 3_450_000

    async def test_map_library_counts_the_unmapped_items(self):
        payload = {
            "libraryItem": {
                "tt0111161": {"type": "movie", "name": "Shawshank", "timeOffset": 100},
                "tt0944947": {"type": "series", "name": "GoT", "watched": {"S1E1": 1.0}},
                "local123": {"type": "movie", "name": "A Local File"},
            }
        }
        mapped, unmapped = map_library(payload)
        assert unmapped == 1  # the non-IMDb id
        assert any(m.id == "tt0111161" for m in mapped)


class TestIds:
    def test_parse_episode_id_splits_a_series_id_and_leaves_a_movie(self):
        assert parse_episode_id("tt0944947:1:2") == ("tt0944947", 1, 2)
        assert parse_episode_id("tt0111161") is None

    def test_parse_watched_key_reads_s_e_numbers(self):
        assert parse_watched_key("S1E12") == (1, 12)
        assert parse_watched_key("s2e4") == (2, 4)
        assert parse_watched_key("nope") is None
