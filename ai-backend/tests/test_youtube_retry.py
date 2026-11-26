"""A refused (HTTP 403) yt-dlp call is retried with the next player client before it fails."""

from __future__ import annotations

import pytest
import yt_dlp

from utubot.youtube import (
    is_forbidden_error,
    retry_forbidden,
)


def forbidden() -> yt_dlp.utils.YoutubeDLError:
    return yt_dlp.utils.YoutubeDLError("HTTP Error 403: Forbidden")


def network() -> yt_dlp.utils.YoutubeDLError:
    return yt_dlp.utils.YoutubeDLError("unable to download: connection refused")


def test_a_non_forbidden_error_is_raised_without_a_retry() -> None:
    calls: list[str] = []

    def run(player: str) -> str:
        calls.append(player)
        raise network()

    with pytest.raises(yt_dlp.utils.YoutubeDLError):
        retry_forbidden(run, ["web", "android"], 0.0)
    assert calls == ["web"]  # only the first player was tried


def test_a_forbidden_error_is_retried_with_the_next_player() -> None:
    calls: list[str] = []

    def run(player: str) -> str:
        calls.append(player)
        if player == "web":
            raise forbidden()
        return "ok"

    assert retry_forbidden(run, ["web", "android"], 0.0) == "ok"
    assert calls == ["web", "android"]


def test_the_last_player_fails_the_call() -> None:
    calls: list[str] = []

    def run(player: str) -> str:
        calls.append(player)
        raise forbidden()

    with pytest.raises(yt_dlp.utils.YoutubeDLError):
        retry_forbidden(run, ["web", "android"], 0.0)
    assert calls == ["web", "android"]  # every player was tried


def test_the_backoff_is_waited_between_the_players(monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("utubot.youtube.time.sleep", lambda s: sleeps.append(s))

    def run(player: str) -> str:
        if player == "web":
            raise forbidden()
        return "ok"

    retry_forbidden(run, ["web", "android"], 2.5)
    assert sleeps == [2.5]  # one wait, between the two players


def test_only_a_forbidden_error_is_retryable() -> None:
    assert is_forbidden_error(forbidden())
    assert not is_forbidden_error(network())
    assert not is_forbidden_error(ValueError("this video is private"))
