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


def test_a_client_specific_refusal_is_retried_with_another_player_client():
    for text in (
        "ERROR: [youtube] abc: Requested format is not available. Use --list-formats",
        "ERROR: [youtube] abc: Video unavailable. This content isn't available, try again later.",
    ):
        calls: list[str] = []

        def run(player, text=text, calls=calls):
            calls.append(player)
            if player == "web":
                raise yt_dlp.utils.DownloadError(text)
            return "ok"

        assert is_forbidden_error(yt_dlp.utils.DownloadError(text))
        assert retry_forbidden(run, ["web", "android"], 0.0) == "ok"
        assert calls == ["web", "android"]


def test_a_removed_or_private_video_is_never_retried():
    for text in (
        "ERROR: Private video. Sign in if you've been granted access",
        "ERROR: Video unavailable. This video has been removed by the uploader",
        "ERROR: This video is no longer available, try again later is not offered",
    ):
        assert not is_forbidden_error(yt_dlp.utils.DownloadError(text))


def test_refusals_of_a_download_classify_as_a_refusal_and_gone_ones_as_unavailable():
    from utubot.youtube import REASON_FORBIDDEN_MEDIA, REASON_UNAVAILABLE, classify_failure

    refused = classify_failure(
        yt_dlp.utils.DownloadError("Requested format is not available"), 60.0, media=True
    )
    assert refused.reason == REASON_FORBIDDEN_MEDIA and refused.can_transcribe
    gone = classify_failure(
        yt_dlp.utils.DownloadError("Video unavailable. This video has been removed"),
        60.0,
        media=True,
    )
    assert gone.reason == REASON_UNAVAILABLE
