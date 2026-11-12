from __future__ import annotations

import json

import httpx
import pytest

from utubot.prompts import PromptError, PromptStore, validate_prompt_set
from utubot.urlguard import UrlRejected, is_blocked_ip, validate_url

VID = "abcdefghijk"
PUBLIC_IP = "93.184.216.34"
HOSTS = {
    "host": [PUBLIC_IP],
    "evil.example": [PUBLIC_IP],
    "internal.example": ["10.0.0.5"],
    "tail.example": ["100.64.0.7"],
    "mapped.example": ["::ffff:10.0.0.1"],
}


async def fake_resolver(host, port):
    if host not in HOSTS:
        raise UrlRejected("host could not be resolved")
    return HOSTS[host]


def pset(set_id="mine", template="Q {title}\n{transcript}", extra=None):
    data = {
        "tubeai_prompt_set": 1,
        "id": set_id,
        "name": "Mine",
        "version": "1",
        "prompts": [
            {
                "id": "p1",
                "label": "P1",
                "system": "sys {language}",
                "template": template,
                "max_tokens": 200,
            }
        ],
    }
    data.update(extra or {})
    return data


async def test_builtin_listed_and_default(env):
    r = await env.client.get("/v1/prompts")
    body = r.json()
    assert body["default"] == "builtin/tldr"
    builtin = next(s for s in body["sets"] if s["id"] == "builtin")
    assert len(builtin["prompts"]) == 6
    assert (await env.client.delete("/v1/prompts/sets/builtin")).status_code == 400
    assert (
        await env.client.put("/v1/prompts/sets/builtin", json=pset("builtin"))
    ).status_code == 400


async def test_put_validate_and_default(env):
    bad = pset()
    bad["prompts"].append(dict(bad["prompts"][0]))
    r = await env.client.put("/v1/prompts/sets/mine", json=bad)
    assert r.status_code == 400 and "duplicate" in r.json()["error"]
    assert (await env.client.put("/v1/prompts/sets/other", json=pset())).status_code == 400
    assert (await env.client.put("/v1/prompts/sets/mine", json=pset())).status_code == 200
    assert (await env.client.put("/v1/prompts/default", json={"key": "mine/p1"})).status_code == 200
    assert (await env.client.get("/v1/prompts")).json()["default"] == "mine/p1"
    assert (
        await env.client.put("/v1/prompts/default", json={"key": "mine/nope"})
    ).status_code == 404
    await env.client.delete("/v1/prompts/sets/mine")
    assert (await env.client.get("/v1/prompts")).json()["default"] == "builtin/tldr"


async def test_import_url_redirect_size_cap_and_refresh(cfg, env):
    served = {"body": json.dumps(pset(template="v1 {transcript}"))}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/short":
            return httpx.Response(302, headers={"location": "https://host/real.json"})
        if request.url.path == "/real.json":
            return httpx.Response(200, content=served["body"])
        if request.url.path == "/huge":
            return httpx.Response(200, content=b"x" * (cfg.summary.max_import_bytes + 10))
        return httpx.Response(404)

    env.svc.prompts._transport = httpx.MockTransport(handler)
    env.svc.prompts._resolver = fake_resolver
    r = await env.client.post("/v1/prompts/import", json={"url": "https://host/short"})
    assert r.status_code == 200 and r.json()["source_url"] == "https://host/short"
    assert (
        await env.client.post("/v1/prompts/import", json={"url": "https://host/huge"})
    ).status_code == 400
    assert (await env.client.post("/v1/prompts/import", json={"url": "ftp://x"})).status_code == 400
    assert (
        await env.client.post("/v1/prompts/import", json={"url": "https://host/none"})
    ).status_code == 400
    served["body"] = json.dumps(pset(template="v2 {transcript}"))
    refreshed = await env.client.post("/v1/prompts/refresh")
    assert refreshed.json()["refreshed"] == {"mine": "ok"}
    got = await env.client.get("/v1/prompts/sets/mine")
    assert got.json()["prompts"][0]["template"] == "v2 {transcript}"


def test_validation_errors():
    import pytest

    from utubot.prompts import PromptError

    for broken in (
        {},
        {"tubeai_prompt_set": 2, "id": "a", "name": "n", "prompts": []},
        pset(extra={"id": "bad id!"}),
        pset(extra={"prompts": [{"id": "x", "label": "l", "template": "t", "max_tokens": 1}]}),
    ):
        with pytest.raises(PromptError):
            validate_prompt_set(broken)
    assert PromptStore  # imported for type clarity


async def test_summary_ready_cached_and_default(env):
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    body = r.json()
    assert body["status"] == "ready" and body["prompt"] == "builtin/tldr"
    assert body["source"] == "youtube_captions" and "SUMMARY[worker]" in body["text"]
    n = len(env.llm.calls)
    again = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert again.json()["text"] == body["text"] and len(env.llm.calls) == n


async def test_summary_cache_invalidates_on_prompt_edit(env):
    await env.client.put("/v1/prompts/sets/mine", json=pset(template="A {transcript}"))
    p = {"prompt": "mine/p1", "wait_ms": 5000}
    await env.client.get(f"/v1/videos/{VID}/summary", params=p)
    n = len(env.llm.calls)
    await env.client.get(f"/v1/videos/{VID}/summary", params=p)
    assert len(env.llm.calls) == n
    await env.client.put("/v1/prompts/sets/mine", json=pset(template="B {transcript}"))
    await env.client.get(f"/v1/videos/{VID}/summary", params=p)
    assert len(env.llm.calls) == n + 1
    other = await env.client.get(
        f"/v1/videos/{VID}/summary", params={"prompt": "builtin/worth-it", "wait_ms": 5000}
    )
    assert other.json()["status"] == "ready"


async def test_summary_model_override_and_unknown_prompt(env):
    data = pset()
    data["prompts"][0]["model"] = "smart"
    await env.client.put("/v1/prompts/sets/mine", json=data)
    await env.client.get(f"/v1/videos/{VID}/summary", params={"prompt": "mine/p1", "wait_ms": 5000})
    assert env.llm.calls[-1]["model"] == "smart"
    assert (
        await env.client.get(f"/v1/videos/{VID}/summary", params={"prompt": "x/y"})
    ).status_code == 404


async def test_summary_pending_then_ready(env):
    env.llm.delay_s = 0.4
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 50})
    assert r.json()["status"] == "pending"
    import asyncio

    await asyncio.sleep(1.0)
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 50})
    assert r.json()["status"] == "ready"


async def test_summary_failure_is_generic_and_never_uses_the_title(env):
    env.fetcher.fail = True
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert r.json()["status"] == "failed" and "blocked" not in r.json()["error"]
    titled = await env.client.get(
        "/v1/videos/zzzzzzzzzzz/summary", params={"wait_ms": 5000, "title": "Known title"}
    )
    assert titled.json()["status"] == "failed" and titled.json()["text"] is None
    assert env.llm.calls == []


async def test_long_transcript_map_reduce(env):
    env.cfg.summary.token_budget = 200
    env.cfg.summary.chunk_tokens = 100
    env.fetcher.text = "\n".join(f"[00:{i:02d}] line {i} " + "word " * 20 for i in range(40))
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 10000})
    assert r.json()["status"] == "ready"
    maps = [c for c in env.llm.calls if "condense one part" in c["messages"][0]["content"]]
    assert len(maps) > 1
    final = env.llm.calls[-1]["messages"][1]["content"]
    assert len(final) < 200 * 4 + 2000


async def test_adhoc_summary_and_ask_and_insight(env):
    r = await env.client.post(
        f"/v1/videos/{VID}/summary",
        json={"prompt_text": "Say hi about {title}", "system": "be brief", "wait_ms": 5000},
    )
    assert r.json()["status"] == "ready" and r.json()["prompt"] == "adhoc"
    a = await env.client.post(f"/v1/videos/{VID}/ask", json={"question": "Why?", "wait_ms": 5000})
    assert a.json() == {
        "answer": "ANSWER: forty-two",
        "status": "ready",
        "transcript_status": "ok",
    }
    i = await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    body = i.json()
    assert body["status"] == "ready" and body["key_points"] == ["a", "b"]
    assert body["inflation"] == {"duration_s": 900, "essential_s": 100, "ratio": 0.111}
    assert body["source"] == "youtube_captions"


def make_store(env, handler, allow=()):
    store = PromptStore(env.svc.cfg, env.svc.db, httpx.MockTransport(handler), fake_resolver)
    env.svc.cfg.summary.import_allow_hosts = list(allow)
    return store


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/x.json",
        "http://127.0.0.1/x.json",
        "http://100.64.0.7/x.json",
        "http://10.0.0.1/x.json",
        "http://[::1]/x.json",
        "http://[::ffff:10.0.0.1]/x.json",
        "http://[2002:c0a8:0101::1]/x.json",
        "http://[fd00::1]/x.json",
        "http://169.254.169.254/x.json",
        "http://0.0.0.0/x.json",
        "http://224.0.0.1/x.json",
        "https://internal.example/x.json",
        "https://tail.example/x.json",
        "https://mapped.example/x.json",
        "https://host:8443/x.json",
        "file:///etc/passwd",
    ],
)
async def test_import_blocks_internal_targets(env, url):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=b"{}")

    store = PromptStore(env.svc.cfg, env.svc.db, httpx.MockTransport(handler), _localhost_resolver)
    with pytest.raises(PromptError):
        await store.fetch(url)
    assert not calls


async def _localhost_resolver(host, port):
    return ["127.0.0.1"] if host == "localhost" else await fake_resolver(host, port)


async def test_import_redirect_to_private_blocked_and_pinned(env):
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers["host"]))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "http://internal.example/secret"})
        return httpx.Response(200, content=b"SECRETBODY")

    store = make_store(env, handler)
    with pytest.raises(PromptError) as err:
        await store.fetch("https://evil.example/start")
    assert "SECRETBODY" not in str(err.value)
    assert seen == [(PUBLIC_IP, "evil.example")]


async def test_import_redirect_limit(env):
    def handler(request):
        return httpx.Response(302, headers={"location": "https://host/again"})

    with pytest.raises(PromptError, match="redirects"):
        await make_store(env, handler).fetch("https://host/again")


async def test_import_allowlisted_host_bypasses_ip_check(env):
    def handler(request):
        return httpx.Response(200, content=json.dumps(pset()).encode())

    store = make_store(env, handler, allow=["internal.example"])
    assert (await store.fetch("https://internal.example:8443/x.json")).id == "mine"
    with pytest.raises(PromptError):
        await make_store(env, handler).fetch("https://internal.example/x.json")


async def test_import_error_does_not_echo_body(env):
    def handler(request):
        return httpx.Response(500, content=b"db password hunter2 at 10.0.0.9")

    with pytest.raises(PromptError) as err:
        await make_store(env, handler).fetch("https://host/x")
    assert "hunter2" not in str(err.value)


def test_is_blocked_ip():
    import ipaddress

    assert not is_blocked_ip(ipaddress.ip_address(PUBLIC_IP))
    assert is_blocked_ip(ipaddress.ip_address("100.64.0.1"))
    assert is_blocked_ip(ipaddress.ip_address("2001:db8::1"))


async def test_validate_url_unresolvable():
    with pytest.raises(UrlRejected):
        await validate_url(httpx.URL("https://nope.example/"), (), fake_resolver)


async def test_upstream_errors_not_leaked(env):
    env.llm.fail_status = 500
    r = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    text = r.text
    assert r.json()["status"] == "failed"
    assert "boom" not in text and "http" not in text and "500" not in text
    again = await env.client.get(f"/v1/videos/{VID}/summary", params={"wait_ms": 5000})
    assert "boom" not in again.text and "http" not in again.text


def test_example_config_loads_with_prod_defaults():
    from pathlib import Path

    from utubot.config import load_config

    cfg = load_config(Path(__file__).parent.parent / "config.example.toml")
    assert cfg.captions.asr_backend == "faster_whisper" and cfg.captions.whisper_threads == 4
    assert cfg.assess.tier2_daily_cap_per_user == 30
    assert cfg.llm.summary.model == "llama3.1:8b" and cfg.llm.triage.model == "llama3.2:3b"
    assert cfg.server.data_dir == "/var/lib/utubot"
