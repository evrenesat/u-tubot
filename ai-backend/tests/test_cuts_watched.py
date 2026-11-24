from __future__ import annotations

import pytest

from tests.synth_video import ffmpeg_available, make_video
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


async def wait_ready(env, request_id: str):
    r = await env.client.get(f"/v1/cuts/{request_id}", params={"wait_ms": 5000})
    return r.json()


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
        job = (await watched_env.client.get(f"/v1/jobs/{second_doc['job_id']}")).json()
        assert "in_line" in {event["stage"] for event in job["events"]}

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
