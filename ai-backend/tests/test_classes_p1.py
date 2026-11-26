from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from tests.conftest import OTHER_TOKEN
from tests.fakes import FakeClock, settle
from tests.synth_video import ffmpeg_available, make_video
from tests.test_webui import PUBLIC, SEGMENT
from utubot.classes import NORMAL, PRIME, ClassGate, bind_class, normalize_class, unbind_class
from utubot.config import LLMTask, UserConfig, YoutubeConfig
from utubot.llm import BACKGROUND, INTERACTIVE, LLMClient, PriorityLimiter
from utubot.watch import watched_deps_installed
from utubot.youtube import YoutubeGate

VID = "abcdefghijk"


def client_for(env, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_unknown_or_client_supplied_class_is_never_prime():
    assert normalize_class("prime") == PRIME
    assert normalize_class("Prime") == NORMAL
    assert normalize_class("admin") == NORMAL
    assert normalize_class(None) == NORMAL


async def test_reserved_prime_slot_is_not_used_by_normal_background():
    limiter = PriorityLimiter(2, reserved_prime=1)
    await limiter.acquire(BACKGROUND, NORMAL)
    blocked = asyncio.create_task(limiter.acquire(BACKGROUND, NORMAL))
    await settle()
    assert not blocked.done()
    await asyncio.wait_for(limiter.acquire(BACKGROUND, PRIME), 1)
    blocked.cancel()
    await asyncio.gather(blocked, return_exceptions=True)
    limiter.release()
    limiter.release()


async def test_the_limiter_reserves_a_prime_slot_only_with_classes(cfg):
    # Without [classes] the route model is used exactly as before: no slot is kept for prime, so
    # normal concurrency is unchanged even though the provider default is reserved_prime = 1.
    assert cfg.classes_configured is False
    assert LLMClient(cfg).limiter("default").reserved_prime == 0
    # With [classes] the provider's reserved_prime applies.
    cfg.classes_configured = True
    assert (
        LLMClient(cfg).limiter("default").reserved_prime
        == cfg.llm.providers["default"].reserved_prime
        == 1
    )


async def test_prime_background_goes_before_normal_interactive():
    limiter = PriorityLimiter(1)
    order: list[str] = []

    async def take(name: str, priority: int, klass: str) -> None:
        await limiter.acquire(priority, klass)
        order.append(name)
        limiter.release()

    await limiter.acquire(BACKGROUND, PRIME)
    normal = asyncio.create_task(take("normal-interactive", INTERACTIVE, NORMAL))
    await settle()
    prime = asyncio.create_task(take("prime-background", BACKGROUND, PRIME))
    await settle()
    limiter.release()
    await asyncio.wait_for(asyncio.gather(normal, prime), 1)
    assert order == ["prime-background", "normal-interactive"]


def youtube_gate(clock: FakeClock) -> YoutubeGate:
    return YoutubeGate(
        YoutubeConfig(min_interval_s=0.0, jitter_s=0.0, max_concurrent=1),
        clock=clock,
        rand=lambda: 0.0,
    )


async def test_youtube_gate_runs_prime_work_before_normal_interactive():
    clock = FakeClock()
    gate = youtube_gate(clock)
    hold = asyncio.Event()
    order: list[str] = []

    async def held() -> None:
        await hold.wait()

    async def named(name: str) -> None:
        order.append(name)

    first = asyncio.create_task(gate.run(held))
    await settle()
    normal = asyncio.create_task(gate.run(lambda: named("normal"), INTERACTIVE, klass=NORMAL))
    await settle()
    prime = asyncio.create_task(gate.run(lambda: named("prime"), BACKGROUND, klass=PRIME))
    await settle()
    hold.set()
    await asyncio.wait_for(asyncio.gather(first, normal, prime), 1)
    assert order == ["prime", "normal"]


async def test_youtube_gate_uses_the_job_class_from_context():
    clock = FakeClock()
    gate = youtube_gate(clock)
    hold = asyncio.Event()
    order: list[str] = []

    async def held() -> None:
        await hold.wait()

    async def named(name: str) -> None:
        order.append(name)

    first = asyncio.create_task(gate.run(held))
    await settle()
    normal = asyncio.create_task(gate.run(lambda: named("normal"), INTERACTIVE))
    await settle()
    token = bind_class(PRIME)
    try:
        prime = asyncio.create_task(gate.run(lambda: named("prime"), BACKGROUND))
    finally:
        unbind_class(token)
    await settle()
    hold.set()
    await asyncio.wait_for(asyncio.gather(first, normal, prime), 1)
    assert order == ["prime", "normal"]


async def test_class_gate_waits_normal_work_once_until_prime_is_done():
    class FakeDB:
        def __init__(self) -> None:
            self.active = True
            self.params: list[list[str]] = []

        def one(self, _sql, params):
            self.params.append(params)
            return {"1": 1} if self.active else None

    db = FakeDB()
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        db.active = False

    gate = ClassGate(db, poll_s=0.01, sleep=sleep)
    seen: list[str] = []
    assert await gate.wait("job", PRIME, lambda: seen.append("prime")) is False
    assert seen == []
    assert await gate.wait("job", NORMAL, lambda: seen.append("normal")) is True
    assert seen == ["normal"]
    assert slept == [0.01]
    assert db.params == [["job", "job"], ["job", "job"]]


async def test_jobs_take_the_class_of_their_user_and_prime_claims_first(env):
    jobs = env.svc.jobs
    await jobs.stop()
    normal = jobs.enqueue_transcript("partner", "normal00001", None)
    env.cfg.users[0].prime = True
    try:
        prime = jobs.enqueue_transcript("owner", "prime000001", None)
    finally:
        env.cfg.users[0].prime = False
    assert normal["klass"] == NORMAL
    assert prime["klass"] == PRIME
    claimed = jobs._claim()
    assert claimed is not None and claimed["id"] == prime["id"]
    assert jobs._claim() is None
    jobs.db.execute("UPDATE jobs SET status='ready' WHERE id=?", [prime["id"]])
    claimed = jobs._claim()
    assert claimed is not None and claimed["id"] == normal["id"]


async def test_a_job_made_with_another_users_token_has_that_users_class(env):
    await env.svc.jobs.stop()
    env.cfg.users[1].prime = True
    other = client_for(env, OTHER_TOKEN)
    try:
        r = await other.post("/v1/videos/extension01/captions", json={"lang": "en"})
        assert r.status_code == 200, r.text
    finally:
        env.cfg.users[1].prime = False
        await other.aclose()
    row = env.svc.db.one("SELECT klass FROM jobs WHERE id=?", [r.json()["job_id"]])
    assert row["klass"] == PRIME


async def test_normal_interactive_work_is_claimed_before_older_background_work(env):
    jobs = env.svc.jobs
    await jobs.stop()
    background = jobs.enqueue_transcript("partner", "background1", None, priority=BACKGROUND)
    interactive = jobs.enqueue_transcript("partner", "interactive", None, priority=INTERACTIVE)
    claimed = jobs._claim()
    assert claimed is not None and claimed["id"] == interactive["id"]
    jobs.db.execute("UPDATE jobs SET status='ready' WHERE id=?", [interactive["id"]])
    claimed = jobs._claim()
    assert claimed is not None and claimed["id"] == background["id"]


async def test_queued_normal_jobs_report_in_line_while_prime_runs(env):
    jobs = env.svc.jobs
    await jobs.stop()
    normal = jobs.enqueue_transcript("partner", "queuednorm1", None)
    running_prime_job(env)
    assert await jobs.run_one() is False
    events = jobs.events.list(normal["id"])
    waiting = [e for e in events if e["stage"] == "in_line"]
    assert waiting and waiting[-1]["detail"]["reason"] == "priority"


async def test_only_demanding_prime_work_pauses_normal(env):
    now = time.time()
    env.svc.db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,"
        "priority,klass) VALUES(?,?,?,'',?,0,?,?,'cuts',?,?)",
        ["prime-cut", "owner", "primecutvid", "running", now, now, INTERACTIVE, PRIME],
    )
    env.svc.db.execute(
        "INSERT INTO cut_requests(id,user,video_id,state,job_id,created_at,updated_at,mode,klass)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        ["prime-req", "owner", "primecutvid", "waiting", "prime-cut", now, now, "watched", PRIME],
    )
    gate = env.svc.jobs.class_gate
    assert gate.prime_active() is False
    env.svc.db.execute("UPDATE cut_requests SET state='needs_transcript' WHERE id='prime-req'")
    assert gate.prime_active() is True
    env.svc.db.execute("UPDATE cut_requests SET mode='quick' WHERE id='prime-req'")
    assert gate.prime_active() is False


async def test_only_a_prime_waiter_raises_the_transcript_class(env):
    jobs = env.svc.jobs
    await jobs.stop()
    normal = jobs.enqueue_transcript("partner", "promotenorm", None)
    jobs.promote_transcript("promotenorm", NORMAL)
    row = env.svc.db.one("SELECT priority,klass FROM jobs WHERE id=?", [normal["id"]])
    assert row["priority"] == INTERACTIVE and row["klass"] == NORMAL
    prime = jobs.enqueue_transcript("partner", "promoteprim", None)
    jobs.promote_transcript("promoteprim", PRIME)
    row = env.svc.db.one("SELECT priority,klass FROM jobs WHERE id=?", [prime["id"]])
    assert row["priority"] == INTERACTIVE and row["klass"] == PRIME


async def test_a_prime_caption_request_promotes_queued_captions(env):
    jobs = env.svc.jobs
    await jobs.stop()
    normal = jobs.enqueue("partner", "promotecap", "en", None)
    assert normal["klass"] == NORMAL
    prime = jobs.enqueue("primejoin", "promotecap", "en", None, klass=PRIME)
    assert prime["id"] == normal["id"]
    row = env.svc.db.one("SELECT priority,klass FROM jobs WHERE id=?", [normal["id"]])
    assert row["priority"] == INTERACTIVE and row["klass"] == PRIME
    promoted = [e for e in jobs.events.list(normal["id"]) if e["stage"] == "promoted"]
    assert promoted and promoted[-1]["detail"]["class"] == PRIME


async def test_an_http_body_cannot_promote_a_job(env):
    await env.svc.jobs.stop()
    r = await env.client.post(
        "/v1/videos/spoofvideo1/captions", json={"lang": "en", "class": "prime"}
    )
    assert r.status_code == 200, r.text
    row = env.svc.db.one("SELECT klass FROM jobs WHERE id=?", [r.json()["job_id"]])
    assert row["klass"] == NORMAL


async def test_spoofed_class_inputs_do_not_promote_the_caller(env):
    me = (
        await env.client.get(
            "/v1/me",
            params={"class": "prime", "prime": "true"},
            headers={"X-Class": "prime", "X-Prime": "true"},
        )
    ).json()
    assert me["prime"] is False and me["class"] == NORMAL
    r = await env.client.post(
        "/v1/videos/spoofvideo2/captions",
        json={"lang": "en", "class": "prime", "prime": True},
    )
    assert r.status_code == 200, r.text
    row = env.svc.db.one("SELECT klass FROM jobs WHERE id=?", [r.json()["job_id"]])
    assert row["klass"] == NORMAL


async def test_me_and_the_user_list_carry_the_class(env):
    me = (await env.client.get("/v1/me")).json()
    assert me["prime"] is False and me["class"] == NORMAL
    env.cfg.users[0].prime = True
    me = (await env.client.get("/v1/me")).json()
    assert me["prime"] is True and me["class"] == PRIME
    users = (await env.client.get("/v1/admin/users")).json()["users"]
    owner = next(u for u in users if u["name"] == "owner")
    assert owner["prime"] is True and owner["class"] == PRIME


async def test_an_admin_can_set_prime_but_not_for_a_config_declared_user(env):
    created = await env.client.post("/v1/users", json={"name": "kid"})
    assert created.status_code == 200, created.text
    r = await env.client.put("/v1/users/kid", json={"prime": True})
    assert r.status_code == 200, r.text
    assert r.json()["prime"] is True and r.json()["class"] == PRIME
    blocked = await env.client.put("/v1/users/partner", json={"prime": True})
    assert blocked.status_code == 409


async def test_a_non_admin_cannot_set_prime(env):
    async with client_for(env, OTHER_TOKEN) as other:
        r = await other.put("/v1/users/partner", json={"prime": True})
    assert r.status_code == 403
    assert next(u for u in env.cfg.users if u.name == "partner").prime is False


def cache_transcript(env, segments):
    env.svc.transcripts.store_meta(VID, {"title": "T", "channel": "C", "duration_s": 60})
    env.svc.db.execute(
        "INSERT OR REPLACE INTO transcripts"
        "(video_id,lang,source,text,fetched_at,segments) VALUES(?,?,?,?,?,?)",
        [
            VID,
            "en",
            "captions",
            " ".join(text for _, _, text in segments),
            time.time(),
            json.dumps(segments),
        ],
    )


def running_prime_job(env, job_id: str = "prime-dummy", kind: str = "captions") -> None:
    now = time.time()
    env.svc.db.execute(
        "INSERT INTO jobs(id,user,video_id,lang,status,progress,created_at,updated_at,kind,"
        "priority,klass) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        [
            job_id,
            "owner",
            "primevideo1",
            "auto",
            "running",
            0.0,
            now,
            now,
            kind,
            INTERACTIVE,
            PRIME,
        ],
    )


async def test_a_shared_build_class_rises_for_a_prime_joiner_only(env, monkeypatch):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    segments = [[i * 5.0, i * 5.0 + 2.5, f"Part {i}."] for i in range(12)]
    cache_transcript(env, segments)
    env.llm.cut_answer = {
        "parts": [{"from": 2, "to": 4, "label": "The demo"}],
        "summary": "The demo part.",
        "kept_s": 15,
    }
    await env.svc.jobs.stop()
    seen: list[str] = []
    captured: dict[str, object] = {}
    hold = asyncio.Event()
    original = env.svc.cuts.engine.pick_parts

    async def blocking(*args, klass=NORMAL, **kwargs):
        captured["klass"] = klass
        seen.append(klass() if callable(klass) else klass)
        await hold.wait()
        return await original(*args, klass=klass, **kwargs)

    monkeypatch.setattr(env.svc.cuts.engine, "pick_parts", blocking)

    async def wait_until(predicate, what: str) -> None:
        for _ in range(300):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for {what}")

    def shared(job_id: str) -> bool:
        return any(
            event["detail"].get("reason") == "shared build"
            for event in env.svc.jobs.events.list(job_id)
        )

    leader = env.svc.cuts.create("owner", VID, preset="cut-demo")
    await wait_until(lambda: bool(seen), "the leader to call the model")
    assert seen == [NORMAL]
    assert captured["klass"]() == NORMAL

    joiner = env.svc.cuts.create("partner", VID, preset="cut-demo")
    await wait_until(lambda: shared(joiner["job_id"]), "the normal joiner")
    assert set(env.svc.cuts._build_class.values()) == {NORMAL}

    env.cfg.users.append(UserConfig(name="primejoin", prime=True))
    prime = env.svc.cuts.create("primejoin", VID, preset="cut-demo")
    await wait_until(lambda: shared(prime["job_id"]), "the prime joiner")
    assert set(env.svc.cuts._build_class.values()) == {PRIME}
    assert captured["klass"]() == PRIME

    hold.set()
    await wait_until(
        lambda: (
            env.svc.db.one("SELECT COUNT(*) AS n FROM cut_requests WHERE state='ready'")["n"] == 3
        ),
        "the shared build",
    )
    assert seen == [NORMAL]
    assert leader["id"] and joiner["id"] and prime["id"]


async def test_a_quick_cut_does_not_wait_behind_prime_work(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.captions.job_poll_s = 0.02
    env.cfg.cuts.poll_s = 0.02
    segments = [[i * 5.0, i * 5.0 + 2.5, f"Part {i}."] for i in range(12)]
    cache_transcript(env, segments)
    await env.svc.jobs.stop()
    running_prime_job(env)
    env.llm.cut_answer = {
        "parts": [{"from": 2, "to": 4, "label": "The demo"}],
        "summary": "The demo part.",
        "kept_s": 15,
    }
    r = await env.client.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
    assert r.status_code == 200, r.text
    request = r.json()
    row = env.svc.db.one("SELECT klass FROM cut_requests WHERE id=?", [request["request_id"]])
    assert row["klass"] == NORMAL
    doc = (
        await env.client.get(f"/v1/cuts/{request['request_id']}", params={"wait_ms": 5000})
    ).json()
    assert doc["state"] == "ready", doc
    stages = [e["stage"] for e in env.svc.jobs.events.list(doc["job_id"])]
    assert "in_line" not in stages


@pytest.mark.skipif(
    not watched_deps_installed() or not ffmpeg_available(),
    reason="ffmpeg and Pillow are required for the watched describing loop",
)
async def test_a_running_normal_watched_build_yields_to_prime(env, tmp_path):
    """A prime watched build takes the single slot from a normal watched build that is describing:
    the normal build pauses after the grid it is on and releases the slot, the prime build runs
    and finishes on its own, then the normal build takes the slot again and finishes with the same
    stored TDT (describing is resumable per grid, so the prime build running in between is the
    preemption the plan describes, not a dismissed request)."""
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.llm.cuts_vision = LLMTask(model="visionmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    env.cfg.cuts.watched.describe_timeout_s = 20.0
    env.cfg.users.append(UserConfig(name="primecut", prime=True))

    # A video in the archive and a transcript; the vision model answers each grid with a delay
    # so the normal build is still describing when the prime build is requested.
    env.svc.archive.store(VID, make_video(tmp_path / VID), kind="video")
    segments: list[tuple[float, float, str]] = []
    at = 0.0
    for i in range(12):
        segments.append((at, at + 2.5, f"Fragment {i} first"))
        segments.append((at + 2.5, at + 5.0, f"Fragment {i} second."))
        at += 5.0
    env.fetcher.segments = segments
    env.fetcher.meta_extra = {"duration_s": int(at)}
    env.llm.delay_s = 0.2
    env.llm.cut_answer = {
        "parts": [{"from": 1, "to": 4, "label": "The demo"}],
        "summary": "The demo.",
        "kept_s": 20,
    }

    async def wait_until(predicate, what: str) -> None:
        for _ in range(800):
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError(f"timed out waiting for {what}")

    def seen_segments() -> list[dict]:
        row = env.svc.db.one(
            "SELECT json FROM scene_descriptions WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            [VID],
        )
        if not row or not row["json"]:
            return []
        return [
            s
            for s in json.loads(row["json"]).get("segments") or []
            if (s.get("analysis_provenance") or {}).get("seen")
        ]

    normal = env.svc.cuts.create("owner", VID, preset="cut-demo", mode="watched")
    await wait_until(
        lambda: len(env.llm.describe_calls) >= 1, "the normal build to describe a grid"
    )

    # A prime watched build for the same video is requested while the normal one is describing.
    prime = env.svc.cuts.create("primecut", VID, preset="cut-demo", mode="watched")

    # The normal build stops after the grid it was on; it does not run the whole describing stage.
    doc = None
    for _ in range(400):
        doc = env.svc.cuts.get(normal["id"], "owner")
        if doc is not None and doc.get("stage") == "in_line":
            break
        await asyncio.sleep(0.01)
    assert doc is not None and doc.get("stage") == "in_line", doc
    assert doc["reason"] == "priority"
    assert doc["message"] == "Waiting for a priority job."
    assert len(env.llm.describe_calls) >= 1, "the normal build yielded before describing a grid"

    # The grids described before the yield are stored; the build resumes and finishes the rest.
    before = seen_segments()
    assert len(before) >= 1
    kept_summary = before[0].get("visual_summary")

    # The prime build takes the slot the normal build released, describes the rest and finishes
    # on its own; it is not dismissed, so the preemption really happened.
    prime_ready = None
    for _ in range(800):
        prime_ready = env.svc.cuts.get(prime["id"], "primecut")
        if prime_ready is not None and prime_ready.get("state") == "ready":
            break
        await asyncio.sleep(0.01)
    assert prime_ready is not None and prime_ready.get("state") == "ready", prime_ready
    assert prime_ready["cut"]["mode"] == "watched"

    # No prime demanding work remains, so the normal build takes the slot again and resumes.
    ready = None
    for _ in range(800):
        ready = env.svc.cuts.get(normal["id"], "owner")
        if ready is not None and ready.get("state") == "ready":
            break
        await asyncio.sleep(0.01)
    assert ready is not None and ready.get("state") == "ready", ready
    cut = ready["cut"]
    assert cut["mode"] == "watched"

    # Resumable per grid: the stored TDT now has every grid seen, and the one described before the
    # yield is still there unchanged, so the build continued where it stopped.
    after = seen_segments()
    total_grids = cut["watched"]["grids"]
    assert len(after) == total_grids >= len(before)
    assert any(s.get("visual_summary") == kept_summary for s in after)


async def test_a_running_normal_caption_job_yields_to_a_prime_job(env, monkeypatch):
    """The single caption worker runs one job at a time, so a normal job that yields to a prime job
    must free the worker to run it: it yields at a safe point, goes back into the queue, the prime
    job runs first, then the normal job resumes and finishes. Without this the worker stays blocked
    on the yield, the queued prime job can never be claimed, and neither job finishes."""
    from utubot.captions.pipeline import AsrTranscript

    env.fetcher.text = None  # no usable captions on YouTube: the track is built from the audio
    prime_queued = False

    async def transcribe(video_id, progress, *, priority, language, klass=None, yield_check=None):
        nonlocal prime_queued
        if yield_check is not None:
            if not prime_queued:
                prime_queued = True
                env.svc.jobs.enqueue_transcript("owner", "primevid", "t", INTERACTIVE, klass=PRIME)
            # Prime demanding work is now queued: yielding raises JobYielded (freeing the worker);
            # once the prime job is gone it returns and the job continues to completion.
            await yield_check()
        return AsrTranscript("[00:00] Hello.", "en", [], "mac", "m")

    monkeypatch.setattr(env.svc.jobs.pipeline, "transcribe", transcribe)
    queue = env.svc.jobs
    await queue.stop()  # drive the one worker by hand so a blocked worker cannot claim the prime
    normal = queue.enqueue_transcript("owner", VID, "t", INTERACTIVE)

    # The normal job starts running, a prime demanding job arrives, and the normal job yields back
    # to the queue instead of holding the one worker; the prime job is queued behind it.
    assert await queue.run_one() is True
    assert queue.db.one("SELECT status FROM jobs WHERE id=?", [normal["id"]])["status"] == "queued"
    prime = queue.db.one("SELECT id, status, klass FROM jobs WHERE video_id='primevid'")
    assert prime["status"] == "queued" and prime["klass"] == PRIME

    # The worker now claims the prime job (prime goes first) and finishes it.
    assert await queue.run_one() is True
    assert queue.db.one("SELECT status FROM jobs WHERE id=?", [prime["id"]])["status"] == "ready"

    # No prime demanding work remains, so the normal job takes the worker again and finishes.
    assert await queue.run_one() is True
    assert queue.db.one("SELECT status FROM jobs WHERE id=?", [normal["id"]])["status"] == "ready"
    assert (
        env.svc.transcripts.cached(VID) is not None
        and env.svc.transcripts.cached(VID).source == "asr"
    )


async def test_the_llm_defaults_to_the_class_bound_for_the_call(env, monkeypatch):
    seen: list[str | None] = []
    original = env.svc.llm._call

    async def recording(provider, body, priority, deadline_at, klass=None):
        seen.append(klass)
        return await original(provider, body, priority, deadline_at, klass=klass)

    monkeypatch.setattr(env.svc.llm, "_call", recording)
    task = env.cfg.llm.summary
    messages = [{"role": "user", "content": "hello"}]
    token = bind_class(PRIME)
    try:
        await env.svc.llm.complete(task, messages)
    finally:
        unbind_class(token)
    assert seen == [PRIME]
    await env.svc.llm.complete(task, messages)
    assert seen == [PRIME, NORMAL]


async def test_a_direct_request_binds_the_authenticated_users_class(env, monkeypatch):
    seen: list[str | None] = []
    original = env.svc.llm._call

    async def recording(provider, body, priority, deadline_at, klass=None):
        seen.append(klass)
        return await original(provider, body, priority, deadline_at, klass=klass)

    monkeypatch.setattr(env.svc.llm, "_call", recording)
    cache_transcript(env, [[0.0, 2.0, "Cached."]])
    env.cfg.users[0].prime = True
    r = await env.client.get(f"/v1/videos/{VID}/summary")
    assert r.status_code == 200, r.text
    assert seen and seen[-1] == PRIME


async def test_no_route_takes_a_class_from_headers_query_or_body(env, monkeypatch):
    await env.svc.jobs.stop()
    await env.svc.cuts.stop()
    cache_transcript(env, [[0.0, 2.0, "Cached."]])
    seen: list[str | None] = []
    original = env.svc.llm._call

    async def recording(provider, body, priority, deadline_at, klass=None):
        seen.append(klass)
        return await original(provider, body, priority, deadline_at, klass=klass)

    monkeypatch.setattr(env.svc.llm, "_call", recording)
    spoof = {"prime": "true", "class": "prime", "klass": "prime"}
    other = httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {OTHER_TOKEN}", **spoof},
        timeout=10.0,
    )
    checked = 0
    try:
        for route in env.app.routes:
            methods = getattr(route, "methods", None)
            if not methods:
                continue
            for method in sorted(methods - {"HEAD", "OPTIONS"}):
                if (method, route.path) in PUBLIC:
                    continue
                url = SEGMENT.sub("abcdefghijk", route.path)
                body = spoof_for(method, route.path)
                res = await other.request(
                    method,
                    url,
                    params=spoof,
                    json=body if method in ("POST", "PUT", "PATCH") else None,
                )
                assert res.status_code < 500, f"{method} {route.path}: {res.text}"
                checked += 1
    finally:
        await other.aclose()
    assert checked >= 40
    for table in ("jobs", "cut_requests"):
        row = env.svc.db.one(f"SELECT COUNT(*) AS n FROM {table} WHERE klass!='normal'")
        assert row["n"] == 0, table
    assert seen and set(seen) == {NORMAL}


def spoof_for(method: str, path: str) -> dict:
    body: dict = {"prime": True, "class": "prime", "klass": "prime"}
    if path == "/v1/videos/{video_id}/summary" and method == "POST":
        body.update(prompt_text="Summarise this video.", wait_ms=0)
    elif path == "/v1/videos/{video_id}/ask":
        body.update(question="What is the answer?", wait_ms=0)
    elif path == "/v1/videos/{video_id}/cuts":
        body.update(await_prompt=True)
    elif path == "/v1/cut-requests/{request_id}" and method == "PUT":
        body.update(prompt="The best bits")
    elif path == "/v1/cut-presets":
        body.update(label="Spoof", prompt="The best bits")
    elif path == "/v1/assess":
        body.update(videos=[{"video_id": VID}], wait_ms=0)
    elif path == "/v1/users" and method == "POST":
        body.update(name="spoofed")
    elif path == "/v1/users/{name}/password":
        body.update(password="correct horse battery staple")
    elif path == "/v1/videos/resolve":
        body.update(text=VID)
    elif path == "/v1/prompts/import":
        body.update(url="http://127.0.0.1:9/none")
    elif path in ("/v1/prompts/default", "/v1/prompts/panel-default"):
        body.update(key="summary")
    elif path == "/v1/feedback":
        body.update(video_id=VID, kind="spoiler", correct=True)
    elif path == "/v1/me/password":
        body.update(new_password="correct horse battery staple")
    elif path == "/v1/admin/pair":
        body.update(user="partner")
    elif path == "/v1/users/{name}":
        body.update(admin=False)
    return body
