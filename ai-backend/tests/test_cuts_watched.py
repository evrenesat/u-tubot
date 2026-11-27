from __future__ import annotations

import asyncio
import time

import pytest

from tests.synth_video import ffmpeg_available, make_video
from tests.test_job_report import event
from utubot.config import LLMTask
from utubot.watch import watched_deps_installed

VID = "abcdefghijk"
pytestmark = pytest.mark.skipif(
    not watched_deps_installed() or not ffmpeg_available(), reason="ffmpeg and Pillow are required"
)


@pytest.fixture
async def watched_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.llm.cuts_vision = LLMTask(model="visionmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    env.cfg.cuts.watched.describe_timeout_s = 20.0
    return env


def set_transcript(fetcher, *, n: int = 12, seconds_each: float = 5.0):
    segs = []
    at = 0.0
    for i in range(n):
        segs.append((at, at + seconds_each / 2, f"Fragment {i} first part"))
        segs.append((at + seconds_each / 2, at + seconds_each, f"Fragment {i} second part."))
        at += seconds_each
    fetcher.segments = segs
    fetcher.meta_extra = {"duration_s": int(at)}
    return segs


async def store_video(env, tmp_path):
    video = make_video(tmp_path / VID)
    env.svc.archive.store(VID, video, kind="video")
    return video


async def post_watched(env, preset="cut-demo", **body):
    payload = {"preset": preset, "mode": "watched", **body}
    return await env.client.post(f"/v1/videos/{VID}/cuts", json=payload)


WAIT_POLL_MS = 5000
WAIT_DEADLINE_S = 120
FINAL_STATES = ("ready", "failed")


async def wait_ready(env, request_id: str):
    """Long-poll until the request ends; one poll can time out on a loaded runner."""
    deadline = time.monotonic() + WAIT_DEADLINE_S
    while True:
        r = await env.client.get(f"/v1/cuts/{request_id}", params={"wait_ms": WAIT_POLL_MS})
        doc = r.json()
        if doc.get("state") in FINAL_STATES or time.monotonic() > deadline:
            return doc


class TestWatchedBuild:
    async def test_builds_a_picture_aware_cut_with_descriptions(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 4, "label": "The demo"}],
            "summary": "The demo.",
            "kept_s": 20,
        }
        r = await post_watched(watched_env)
        assert r.status_code == 200, r.text
        doc = await wait_ready(watched_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc["error"]
        cut = doc["cut"]
        assert cut["mode"] == "watched"
        assert cut["watched"]["model"] == "visionmodel"
        assert cut["watched"]["grids"] == len(watched_env.llm.describe_calls)
        assert cut["watched"]["partial"] is False
        assert cut["watched"]["coarse"] is False
        assert watched_env.llm.describe_calls, "the watched path described no grid"
        call = watched_env.llm.describe_calls[0]
        assert call["model"] == "visionmodel"
        assert call["images"] and call["images"][0].startswith("data:image/jpeg;base64,")
        assert "Scene timing" in call["text"]
        me = (await watched_env.client.get("/v1/me")).json()
        assert me["features"]["cuts_watched"] is True
        labels = watched_env.svc.db.all(
            "SELECT * FROM scene_labels WHERE source_key=? ORDER BY start_ms", [f"youtube:{VID}"]
        )
        assert len(labels) == cut["watched"]["grids"]
        assert labels[0]["category"] == "violence" and labels[0]["vocab_version"] == 1
        job = (await watched_env.client.get(f"/v1/jobs/{doc['job_id']}")).json()
        stages = {event["stage"] for event in job["events"]}
        assert {"transcript", "video", "grids", "describing", "model", "checking"} <= stages

    async def test_other_preset_reuses_the_descriptions_and_grids(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        first = await post_watched(watched_env, preset="cut-no-filler")
        await wait_ready(watched_env, first.json()["request_id"])
        described = len(watched_env.llm.describe_calls)
        second = await post_watched(watched_env, preset="cut-highlights-5")
        doc = await wait_ready(watched_env, second.json()["request_id"])
        assert doc["state"] == "ready"
        assert len(watched_env.llm.describe_calls) == described
        assert not list((watched_env.svc.cfg.media_dir / "watched").rglob("*.jpg"))

    async def test_a_second_watched_build_reuses_the_archived_video(self, watched_env, tmp_path):
        # the small copy is downloaded once, kept in the archive, and reused by every later build
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        first = await post_watched(watched_env, preset="cut-no-filler")
        first_doc = await wait_ready(watched_env, first.json()["request_id"])
        assert first_doc["state"] == "ready", first_doc.get("error")
        assert (
            event(watched_env, first_doc["job_id"], "video", "ok")["detail"]["source"]
            == "from_archive"
        )
        described = len(watched_env.llm.describe_calls)
        second = await post_watched(watched_env, preset="cut-highlights-5")
        second_doc = await wait_ready(watched_env, second.json()["request_id"])
        assert second_doc["state"] == "ready"
        # the second build downloads nothing and re-describes nothing: it reuses the archive + grids
        assert (
            event(watched_env, second_doc["job_id"], "video", "ok")["detail"]["source"]
            == "from_archive"
        )
        assert (
            event(watched_env, second_doc["job_id"], "describing", "skipped")["detail"]["reason"]
            == "cached"
        )
        assert len(watched_env.llm.describe_calls) == described

    async def test_failure_offers_the_ready_quick_cut_when_one_exists(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 4, "label": "The demo"}],
            "summary": "s",
            "kept_s": 20,
        }
        quick = await watched_env.client.post(
            f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo", "mode": "quick"}
        )
        quick_doc = await wait_ready(watched_env, quick.json()["request_id"])
        assert quick_doc["state"] == "ready", quick_doc.get("error")
        watched_env.llm.describe_answer = lambda text, images: {
            "visual_summary": "x",
            "kind": "film_scene",
            "on_screen_text": "",
            "same_as_previous": False,
        }
        r = await post_watched(watched_env)
        doc = await wait_ready(watched_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert doc["fallback"]["mode"] == "quick" and doc["fallback"]["state"] == "ready"
        assert doc["fallback"]["cut"]["mode"] == "quick"

    async def test_a_second_watched_build_waits_in_line(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.delay_s = 0.5
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 4, "label": "The demo"}],
            "summary": "s",
            "kept_s": 20,
        }
        first = await post_watched(watched_env, preset="cut-demo")
        second = await post_watched(watched_env, preset="cut-highlights-5")
        first_doc = await wait_ready(watched_env, first.json()["request_id"])
        assert first_doc["state"] == "ready", first_doc.get("error")
        second_doc = await wait_ready(watched_env, second.json()["request_id"])
        assert second_doc["state"] == "ready"
        # Both cuts wait for the same transcript and become ready together, so either may take the
        # slot first; the other one waits in line.
        stages = []
        for jid in (first_doc["job_id"], second_doc["job_id"]):
            job = (await watched_env.client.get(f"/v1/jobs/{jid}")).json()
            stages.append({event["stage"] for event in job["events"]})
        assert sum("in_line" in s for s in stages) == 1, stages

    async def test_failure_offers_quick_instead(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)

        def bad(text, images):
            return {
                "visual_summary": "x",
                "kind": "film_scene",
                "on_screen_text": "",
                "same_as_previous": False,
            }

        watched_env.llm.describe_answer = bad
        r = await post_watched(watched_env)
        doc = await wait_ready(watched_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "seen" in doc["error"] or "describe" in doc["error"]
        assert doc["fallback"]["mode"] == "quick"
        assert doc["fallback"]["state"] == "none"

    async def test_an_upstream_http_400_retries_with_half_context(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        watched_env.llm.describe_400_first = 1
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 4, "label": "The demo"}],
            "summary": "s",
            "kept_s": 20,
        }
        r = await post_watched(watched_env)
        doc = await wait_ready(watched_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        assert len(watched_env.llm.describe_calls) == doc["cut"]["watched"]["grids"]

    async def test_long_videos_fail_before_the_video_download(self, watched_env):
        watched_env.cfg.cuts.watched.max_video_minutes = 1
        set_transcript(watched_env.fetcher, n=12, seconds_each=10.0)
        watched_env.svc.transcripts.store_meta(VID, {"duration_s": 120})
        assert watched_env.cfg.cuts.watched.max_video_minutes == 1
        assert watched_env.svc.cfg.cuts.watched.max_video_minutes == 1
        r = await post_watched(watched_env)
        doc = await wait_ready(watched_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "longer" in doc["error"]
        assert doc["fallback"] == {"mode": "quick", "state": "none"}
        assert watched_env.svc.archive.lookup(VID, "video") is None

    async def test_missing_pillow_is_a_plain_unavailable_reason(self, env, monkeypatch):
        import importlib.util

        def no_pillow(name):
            return None if name == "PIL" else importlib.util.find_spec(name)

        monkeypatch.setattr(importlib.util, "find_spec", no_pillow)
        state = (await env.client.get(f"/v1/videos/{VID}/cuts")).json()
        watched = next(mode for mode in state["modes"] if mode["id"] == "watched")
        assert watched["available"] is False and "not installed" in watched["reason"]
        assert (await env.client.get("/v1/me")).json()["features"]["cuts_watched"] is False

    async def test_watched_listed_unavailable_without_a_vision_model(self, env):
        env.cfg.llm.cuts = LLMTask(model="cutmodel")
        state = (await env.client.get(f"/v1/videos/{VID}/cuts")).json()
        watched = next(mode for mode in state["modes"] if mode["id"] == "watched")
        assert watched["available"] is False and "not configured" in watched["reason"]
        assert state["default_mode"] == "quick"
        me = (await env.client.get("/v1/me")).json()
        assert me["features"]["cuts_watched"] is False
        r = await env.client.post(
            f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo", "mode": "watched"}
        )
        assert r.status_code == 409 and "not configured" in r.json()["error"]

    async def test_archive_remove_clears_watched_cache(self, watched_env, tmp_path):
        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        r = await post_watched(watched_env)
        await wait_ready(watched_env, r.json()["request_id"])
        assert (
            watched_env.svc.db.one(
                "SELECT COUNT(*) AS n FROM scene_descriptions WHERE video_id=?", [VID]
            )["n"]
            > 0
        )
        removed = await watched_env.client.delete(f"/v1/admin/archive/{VID}")
        assert removed.status_code == 200 and removed.json()["ok"] is True
        assert removed.json()["watched_cache_rows_removed"]["description_rows"] > 0
        tdt = await watched_env.client.get(f"/v1/admin/videos/{VID}/tdt")
        assert tdt.status_code == 404

    async def test_the_default_mode_follows_the_users_policy(self, watched_env):
        r = await watched_env.client.put(
            "/v1/me/settings", json={"settings": {"cuts": {"cut_mode": "watched"}}}
        )
        assert r.status_code == 200
        state = (await watched_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert state["default_mode"] == "watched"
        watched = next(mode for mode in state["modes"] if mode["id"] == "watched")
        assert watched["default"] is True


OTHER_VID = "bbbbbbbbbbb"
PRIME_DEADLINE_S = 30
LONG_POLL_MS = 1000


async def store_video_as(env, tmp_path, video_id: str):
    video = make_video(tmp_path / video_id)
    env.svc.archive.store(video_id, video, kind="video")


async def post_watched_for(env, video_id: str, preset: str):
    return await env.client.post(
        f"/v1/videos/{video_id}/cuts", json={"preset": preset, "mode": "watched"}
    )


async def wait_until(env, request_id: str, states, deadline_s: float):
    """Long-poll until the request reaches one of `states` (or the deadline); returns the last doc.
    A one-second long poll keeps the calls under the per-token request limit."""
    deadline = time.monotonic() + deadline_s
    doc: dict = {}
    while time.monotonic() < deadline:
        doc = (
            await env.client.get(f"/v1/cuts/{request_id}", params={"wait_ms": LONG_POLL_MS})
        ).json()
        if doc.get("state") in states:
            return doc
    return doc


class HeldTranscript:
    """Stands in for the YouTube fetcher: the caption fetch of one video waits until `release`."""

    def __init__(self, inner, video_id: str):
        self.inner, self.video_id = inner, video_id
        self.release = asyncio.Event()

    async def meta(self, video_id: str):
        return await self.inner.meta(video_id)

    async def __call__(self, video_id: str):
        if video_id == self.video_id:
            await self.release.wait()
        return await self.inner(video_id)


class TestTranscriptWaitHoldsNoSlot:
    async def test_a_prime_cut_builds_while_a_normal_one_waits_for_its_transcript(
        self, watched_env, tmp_path
    ):
        # #165: a normal watched cut waiting for its transcript must not hold the one watched slot,
        # or a prime watched cut waits behind it for the whole transcript wait.
        await store_video(watched_env, tmp_path)
        await store_video_as(watched_env, tmp_path, OTHER_VID)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        held = HeldTranscript(watched_env.svc.transcripts.fetcher, VID)
        watched_env.svc.transcripts.fetcher = held
        # The held fetch must not also hold the only transcript worker and the one YouTube gate
        # slot (the defaults), or the prime video's transcript would queue behind it for reasons
        # that have nothing to do with the watched slot.
        watched_env.cfg.captions.job_concurrency = 2
        await watched_env.svc.jobs.stop()
        watched_env.svc.jobs.start()
        watched_env.svc.gate._limit = 2
        try:
            normal = (await post_watched(watched_env, preset="cut-demo")).json()["request_id"]
            waiting = await wait_until(watched_env, normal, ("needs_transcript",), WAIT_DEADLINE_S)
            assert waiting["state"] == "needs_transcript", waiting
            assert watched_env.svc.cuts._watched_running == 0, "the transcript wait holds the slot"

            owner = watched_env.cfg.users[0]
            owner.prime = True
            try:
                prime = (await post_watched_for(watched_env, OTHER_VID, "cut-highlights-5")).json()[
                    "request_id"
                ]
            finally:
                owner.prime = False
            assert (
                watched_env.svc.db.one("SELECT klass FROM cut_requests WHERE id=?", [prime])[
                    "klass"
                ]
                == "prime"
            )
            prime_doc = await wait_until(watched_env, prime, FINAL_STATES, PRIME_DEADLINE_S)
            assert prime_doc.get("state") == "ready", prime_doc.get("error")
            still = (await watched_env.client.get(f"/v1/cuts/{normal}")).json()
            assert still["state"] == "needs_transcript", still
        finally:
            held.release.set()
        doc = await wait_ready(watched_env, normal)
        assert doc["state"] == "ready", doc.get("error")
        assert watched_env.svc.cuts._watched_running == 0


class TestWatchedSlotLifecycle:
    async def test_a_dismissal_during_a_prime_yield_stops_the_build(
        self, watched_env, tmp_path, monkeypatch
    ):
        from utubot.cuts import CutRefused
        from utubot.watch.service import WatchedBuilder

        await store_video(watched_env, tmp_path)
        set_transcript(watched_env.fetcher)
        cuts = watched_env.svc.cuts
        # The yield sees a prime job once, then none: `_wait_for_prime` waits, then tries the slot.
        armed = {"on": False}
        prime_answers = [True, False]

        def prime_active(exclude_job=None):
            if not armed["on"] or not prime_answers:
                return False
            return prime_answers.pop(0)

        monkeypatch.setattr(watched_env.svc.jobs.class_gate, "prime_active", prime_active)
        outcomes = {"raised": 0, "continued": 0}

        async def build(self_builder, cuts_, request_id, row, trace, prepared, yield_check=None):
            armed["on"] = True
            # Dismissed without cancelling this task (`dismiss` would cancel it): the state alone
            # is what the yield must notice.
            cuts_._set_state(request_id, "dismissed", finished=True)
            try:
                await yield_check()
            except CutRefused:
                outcomes["raised"] += 1
                raise
            outcomes["continued"] += 1
            return {}, "unused"

        monkeypatch.setattr(WatchedBuilder, "build", build)
        request_id = (await post_watched(watched_env)).json()["request_id"]
        deadline = time.monotonic() + WAIT_DEADLINE_S
        while request_id in cuts._tasks and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        assert outcomes == {"raised": 1, "continued": 0}
        assert cuts._watched_running == 0

    async def test_a_refused_prepare_leaves_no_slot_and_the_next_build_runs(
        self, watched_env, tmp_path
    ):
        # A live video is refused in `prepare`, before the watched slot is taken.
        await store_video(watched_env, tmp_path)
        await store_video_as(watched_env, tmp_path, OTHER_VID)
        set_transcript(watched_env.fetcher)
        watched_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        watched_env.svc.transcripts.store_meta(VID, {"is_live": True})
        refused = (await post_watched(watched_env, preset="cut-demo")).json()["request_id"]
        refused_doc = await wait_ready(watched_env, refused)
        assert refused_doc["state"] == "failed", refused_doc
        assert watched_env.svc.cuts._watched_running == 0

        second = (await post_watched_for(watched_env, OTHER_VID, "cut-highlights-5")).json()
        doc = await wait_ready(watched_env, second["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        assert watched_env.svc.cuts._watched_running == 0
