"""Voice prompts: the phone's recording goes to modelgate and only the text comes back."""

from __future__ import annotations

import httpx

from utubot.speech import MSG_BUSY, MSG_EMPTY, MSG_NOT_CONFIGURED, MSG_TOO_LARGE


def speech_cfg(env):
    env.cfg.speech.alias = "stt"
    env.cfg.speech.per_user_per_min = 10
    env.cfg.speech.max_upload_bytes = 4 * 1024 * 1024
    return env.cfg.speech


async def test_a_recording_becomes_text_through_the_alias(env):
    speech_cfg(env)
    recording = b"\x1aE\xdf\xa3 fake webm bytes"

    r = await env.client.post(
        "/v1/speech",
        files={"audio": ("clip.webm", recording, "audio/webm")},
    )

    assert r.status_code == 200, r.text
    assert r.json() == {"text": env.llm.audio_text}
    assert env.llm.audio_calls[-1]["model"] == "stt"


async def test_the_configured_language_rides_along(env):
    speech = speech_cfg(env)
    speech.language = "en"

    r = await env.client.post(
        "/v1/speech", files={"audio": ("clip.m4a", b"aac bytes", "audio/mp4")}
    )

    assert r.status_code == 200, r.text
    assert env.llm.audio_calls[-1] == {"model": "stt", "language": "en"}


async def test_the_file_field_name_is_also_accepted(env):
    speech_cfg(env)

    r = await env.client.post("/v1/speech", files={"file": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 200, r.text
    assert env.llm.audio_calls[-1]["model"] == "stt"


async def test_the_client_language_hint_overrides_the_server_language(env):
    speech = speech_cfg(env)
    speech.language = "tr"  # the server default, sent when the client hints nothing

    r = await env.client.post(
        "/v1/speech",
        files={"audio": ("clip.webm", b"bytes", "audio/webm")},
        data={"language": "en"},
    )

    assert r.status_code == 200, r.text
    assert env.llm.audio_calls[-1] == {"model": "stt", "language": "en"}


async def test_without_a_hint_the_server_language_still_rides(env):
    speech = speech_cfg(env)
    speech.language = "de"

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 200, r.text
    assert env.llm.audio_calls[-1] == {"model": "stt", "language": "de"}


async def test_without_an_alias_it_says_not_configured_and_calls_nothing(env):
    env.cfg.speech.alias = ""

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 503
    assert r.json() == {"error": MSG_NOT_CONFIGURED}
    assert env.llm.audio_calls == []


async def test_an_empty_recording_is_refused_plainly(env):
    speech_cfg(env)

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"", "audio/webm")})

    assert r.status_code == 400
    assert r.json() == {"error": MSG_EMPTY}
    assert env.llm.audio_calls == []


async def test_an_upload_over_the_speech_cap_is_rejected_before_the_read(env):
    speech = speech_cfg(env)
    speech.max_upload_bytes = 8

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"x" * 9, "audio/webm")})

    assert r.status_code == 413
    assert r.json() == {"error": "request too large"}
    assert env.llm.audio_calls == []


async def test_the_other_routes_keep_the_global_small_cap(env):
    speech_cfg(env)
    env.cfg.security.max_body_bytes = 100

    r = await env.client.post(
        "/v1/assess", json={"videos": [{"video_id": "aaaaaaaaaaa"} for _ in range(40)]}
    )

    assert r.status_code == 413
    assert r.json() == {"error": "request too large"}


async def test_the_per_user_rate_limit_stops_a_retry_loop(env):
    speech = speech_cfg(env)
    speech.per_user_per_min = 1

    first = await env.client.post(
        "/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")}
    )
    second = await env.client.post(
        "/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")}
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 429
    assert second.json() == {"error": "rate limited"}


async def test_a_busy_engine_says_try_again_or_type_it(env):
    speech_cfg(env)
    env.llm.audio_status = 503

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 503
    assert r.json() == {"error": MSG_BUSY}


async def test_an_upstream_refusal_says_try_again_or_type_it(env):
    speech_cfg(env)
    env.llm.audio_status = 400

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 502
    assert r.json()["error"] != MSG_TOO_LARGE


async def test_an_unreachable_modelgate_says_try_again_or_type_it(env):
    speech_cfg(env)
    env.cfg.speech.max_upload_bytes = 4 * 1024 * 1024

    def unreachable(_request):
        raise httpx.ConnectError("modelgate is down")

    failing = httpx.MockTransport(unreachable)
    env.svc.speech._http = httpx.AsyncClient(transport=failing, timeout=1.0)

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 503
    assert r.json() == {"error": MSG_BUSY}


async def test_a_bare_filename_gets_the_recording_extension(env):
    speech_cfg(env)

    r = await env.client.post("/v1/speech", files={"audio": ("recording", b"bytes", "audio/webm")})

    assert r.status_code == 200, r.text
    assert env.llm.audio_filenames[-1] == "recording.webm"


async def test_a_missing_provider_is_reported_as_not_configured(env):
    speech_cfg(env)
    env.cfg.speech.provider = "no-such-provider"

    r = await env.client.post("/v1/speech", files={"audio": ("clip.webm", b"bytes", "audio/webm")})

    assert r.status_code == 503
    assert r.json() == {"error": MSG_NOT_CONFIGURED}
    assert env.llm.audio_calls == []
