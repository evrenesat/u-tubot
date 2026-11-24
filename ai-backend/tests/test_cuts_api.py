from __future__ import annotations

import asyncio
import json
import time

import pytest

from tests.conftest import OTHER_TOKEN
from utubot.config import LLMTask
from utubot.youtube import YoutubeVideoError

VID = "abcdefghijk"


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    # Generous: the wait returns the moment the transcript lands, and on a loaded host the
    # real-ffmpeg ASR chain has taken longer than a tight cap, failing the request outright.
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


def set_transcript(fetcher, *, n: int = 12, seconds_each: float = 5.0):
    """A timed transcript: n units of `seconds_each`, one sentence each, with matching metadata."""
    segs = []
    at = 0.0
    for i in range(n):
        segs.append((at, at + seconds_each / 2, f"Fragment {i} first part"))
        segs.append((at + seconds_each / 2, at + seconds_each, f"Fragment {i} second part {i}."))
        at += seconds_each
    fetcher.segments = segs
    fetcher.meta_extra = {"duration_s": int(at)}
    return segs


async def post_cut(env, **body):
    return await env.client.post(f"/v1/videos/{VID}/cuts", json=body)


async def wait_ready(env, request_id: str, *, wait_ms: int = 5000):
    r = await env.client.get(f"/v1/cuts/{request_id}", params={"wait_ms": wait_ms})
    return r.json()


class TestCreateAndBuild:
    async def test_preset_builds_to_ready(self, cuts_env):
        segs = set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 2, "to": 4, "label": "The demo"}],
            "summary": "The demo part.",
            "kept_s": 15,
        }
        r = await post_cut(cuts_env, preset="cut-demo")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["state"] == "building"
        doc = await wait_ready(cuts_env, body["request_id"])
        assert doc["state"] == "ready"
        cut = doc["cut"]
        assert cut["parts"] == [
            {"label": "The demo", "start_ms": 5000 - 300, "end_ms": 20000 + 500}
        ]
        assert cut["skip_ranges_ms"] == [[0, 4700], [20500, segs[-1][1] * 1000]]
        assert cut["model"] == "cutmodel" and cut["preset_id"] == "cut-demo"
        assert cut["duration_ms"] == int(segs[-1][1]) * 1000
        # The report carries the model answer and the job id.
        assert json.loads(doc["raw_answer"])["summary"] == "The demo part."
        assert doc["job_id"]

    async def test_queue_card_carries_video_facts_and_source(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        r = await post_cut(cuts_env, preset="cut-no-filler")
        rid = r.json()["request_id"]
        q = (await env_queue(cuts_env)).json()["requests"]
        card = next(c for c in q if c["id"] == rid)
        assert card["title"] == f"Title {VID}" and card["channel"] == "Chan"
        assert card["duration_s"] == 60
        assert card["source"] == "API token"
        assert card["preset_id"] == "cut-no-filler"

    async def test_ready_cut_is_shared_between_users_and_repeats(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        first = (await post_cut(cuts_env, preset="cut-answer")).json()
        await wait_ready(cuts_env, first["request_id"])
        calls = len(cuts_env.llm.cut_calls)
        # The same user asking again gets a new request that reuses the shared cut.
        second = (await post_cut(cuts_env, preset="cut-answer")).json()
        doc = await wait_ready(cuts_env, second["request_id"])
        assert doc["state"] == "ready" and doc["cut"]["parts"][0]["label"] == "Start"
        assert len(cuts_env.llm.cut_calls) == calls
        # A different user shares it too.
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        other = await partner.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-answer"})
        rid = other.json()["request_id"]
        r = await partner.get(f"/v1/cuts/{rid}", params={"wait_ms": 5000})
        assert r.json()["state"] == "ready"
        assert len(cuts_env.llm.cut_calls) == calls

    async def test_builds_in_flight_together_share_one_model_call(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 3, "label": "Start"}],
            "summary": "s",
            "kept_s": 15,
        }
        cuts_env.llm.delay_s = 0.3
        first = (await post_cut(cuts_env, preset="cut-answer")).json()
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        # The TV and the phone ask for the same cut while the first is still building.
        second = await partner.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-answer"})
        assert second.status_code == 200
        rid = second.json()["request_id"]
        assert rid != first["request_id"]
        mine, theirs = await asyncio.gather(
            wait_ready(cuts_env, first["request_id"]),
            partner.get(f"/v1/cuts/{rid}", params={"wait_ms": 5000}),
        )
        assert mine["state"] == "ready" and theirs.json()["state"] == "ready"
        assert mine["cut"]["parts"] == theirs.json()["cut"]["parts"]
        assert len(cuts_env.llm.cut_calls) == 1

    async def test_shared_build_survives_the_leader_being_dismissed(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 2, "label": "Ok"}],
            "summary": "s",
            "kept_s": 10,
        }
        cuts_env.llm.delay_s = 0.3
        first = (await post_cut(cuts_env, preset="cut-demo")).json()
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        second = await partner.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
        rid = second.json()["request_id"]

        def model_events(request_id: str) -> list[dict]:
            job = cuts_env.svc.cuts._row(request_id)["job_id"]
            return cuts_env.svc.jobs.events.list(job)

        def shared_build_event(request_id: str) -> dict | None:
            return next(
                (
                    e
                    for e in model_events(request_id)
                    if e["stage"] == "model"
                    and e["status"] == "skipped"
                    and e["detail"].get("reason") == "shared build"
                ),
                None,
            )

        # Which request ends up the waiter depends on timing, so wait until one of them has
        # really joined the other's in-flight build, then dismiss the leader (the other one).
        deadline = time.monotonic() + 5.0
        waiter = None
        while time.monotonic() < deadline:
            waiter = next(
                (r for r in (first["request_id"], rid) if shared_build_event(r) is not None),
                None,
            )
            if waiter is not None:
                break
            await asyncio.sleep(0.02)
        assert waiter is not None, "the second request never joined the leader's build"
        leader = rid if waiter == first["request_id"] else first["request_id"]
        # Each request answers only to its own user, so dismiss and read through their clients.
        owner_of = {first["request_id"]: cuts_env.client, rid: partner}
        await owner_of[leader].delete(f"/v1/cut-requests/{leader}")
        r = await owner_of[waiter].get(f"/v1/cuts/{waiter}", params={"wait_ms": 5000})
        assert r.json()["state"] == "ready"
        # The leader's model call was cancelled inside the mock's delay, so only the
        # rebuild produced an answer.
        assert len(cuts_env.llm.cut_calls) == 1

    async def test_stop_does_not_let_a_cancelled_waiter_start_a_model_call(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 2, "label": "Ok"}],
            "summary": "s",
            "kept_s": 10,
        }
        cuts_env.llm.delay_s = 0.3
        first = (await post_cut(cuts_env, preset="cut-demo")).json()
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        second = await partner.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
        rid = second.json()["request_id"]

        def shared_build(request_id: str) -> bool:
            job = cuts_env.svc.cuts._row(request_id)["job_id"]
            return any(
                e["stage"] == "model"
                and e["status"] == "skipped"
                and e["detail"].get("reason") == "shared build"
                for e in cuts_env.svc.jobs.events.list(job)
            )

        # One of the two joins the other's build; wait until that really happened.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if shared_build(first["request_id"]) or shared_build(rid):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("the second request never joined the leader's build")
        waiter = rid if shared_build(rid) else first["request_id"]
        leader = rid if waiter == first["request_id"] else first["request_id"]

        # The dangerous shutdown interleaving: the leader's task finishes its cancellation
        # first (its `finally` cancels the shared future), and only then the waiter's own
        # cancellation is delivered. A waiter that cannot tell its own cancellation from the
        # leader's dismissal used to rebuild here — a real model call while the server stops.
        # (`stop()` cancels every task at once; this orders the same two cancellations.)
        tasks = cuts_env.svc.cuts._tasks
        tasks[leader].cancel()
        for _ in range(1000):
            if not cuts_env.svc.cuts._inflight:
                break
            await asyncio.sleep(0)
        assert not cuts_env.svc.cuts._inflight, "the leader never freed the cache key"
        # ... while the waiter's wake-up from the cancelled future is still queued
        tasks[waiter].cancel()
        await asyncio.gather(tasks[waiter], return_exceptions=True)
        assert cuts_env.llm.cut_calls == []

    # The dismissal window this test injects (the leader is marked dismissed after the model
    # answered but before its own _finish) does not exist on a real DELETE: a real dismissal
    # cancels the leader's task mid-`_ask`, before any answer. The monkeypatched `_dismissed`
    # is the only way to land in that window deterministically.
    async def test_dismissed_leader_still_hands_its_answer_to_the_waiter(
        self, cuts_env, monkeypatch
    ):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 2, "label": "Ok"}],
            "summary": "s",
            "kept_s": 10,
        }
        cuts_env.llm.delay_s = 0.3
        first = (await post_cut(cuts_env, preset="cut-demo")).json()
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        second = await partner.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
        rid = second.json()["request_id"]

        def model_events(request_id: str) -> list[dict]:
            job = cuts_env.svc.cuts._row(request_id)["job_id"]
            return cuts_env.svc.jobs.events.list(job)

        # The leader is whichever request is still running its own model stage.
        deadline = time.monotonic() + 5.0
        leader = None
        while time.monotonic() < deadline:
            leader = next(
                (
                    r
                    for r in (first["request_id"], rid)
                    if any(
                        e["stage"] == "model" and e["status"] == "running" for e in model_events(r)
                    )
                ),
                None,
            )
            if leader is not None:
                break
            await asyncio.sleep(0.02)
        assert leader is not None, "no request reached its own model stage"
        # A dismissal lands in the window after the model answered but before the build
        # finished: the row is marked dismissed without cancelling the task, so the
        # waiter can only be saved by the leader's own answer.
        monkeypatch.setattr(
            cuts_env.svc.cuts,
            "_dismissed",
            lambda request_id: request_id == leader and bool(cuts_env.llm.cut_calls),
        )
        cuts_env.svc.cuts._set_state(leader, "dismissed", finished=True)
        waiter = rid if leader == first["request_id"] else first["request_id"]
        owner_of = {first["request_id"]: cuts_env.client, rid: partner}
        r = await owner_of[waiter].get(f"/v1/cuts/{waiter}", params={"wait_ms": 5000})
        assert r.json()["state"] == "ready"
        # The leader's completed answer was reused: no second model round-trip.
        assert len(cuts_env.llm.cut_calls) == 1

    async def test_presets_state_moves_none_to_ready(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 2, "label": "Intro"}],
            "summary": "s",
            "kept_s": 10,
        }
        state = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert state["configured"] is True
        entry = {p["id"]: p for p in state["presets"]}
        assert entry["cut-no-filler"]["state"] == "none"
        assert [p["label"] for p in state["presets"]] == [
            "No filler",
            "Just the answer",
            "Only the demo",
            "Highlights in 5 min",
        ]
        r = await post_cut(cuts_env, preset="cut-no-filler")
        await wait_ready(cuts_env, r.json()["request_id"])
        state = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        entry = {p["id"]: p for p in state["presets"]}
        assert entry["cut-no-filler"]["state"] == "ready"
        assert entry["cut-no-filler"]["cut"]["kept_ms"] > 0
        assert entry["cut-answer"]["state"] == "none"

    async def test_typed_prompt_builds(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 3, "to": 4, "label": "Answer"}],
            "summary": "s",
            "kept_s": 10,
        }
        r = await post_cut(cuts_env, prompt="Only the part where they open the box")
        assert r.status_code == 200
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready"
        assert doc["cut"]["source"] == "prompt" and doc["cut"]["preset_id"] is None
        assert doc["cut"]["label"].startswith("Only the part")
        # The prompt went to the model verbatim.
        assert "Only the part where they open the box" in cuts_env.llm.cut_calls[-1]

    async def test_repair_round_fixes_bad_ids(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        good = {"parts": [{"from": 1, "to": 2, "label": "Ok"}], "summary": "s", "kept_s": 10}
        cuts_env.llm.cut_answers = [
            {"parts": [{"from": 40, "to": 99, "label": "Bad"}]},  # ids out of range
            good,
        ]
        r = await post_cut(cuts_env, preset="cut-demo")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready" and len(cuts_env.llm.cut_calls) == 2

    async def test_two_failures_give_a_plain_reason(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answers = [
            {"parts": [{"from": 40, "to": 99}]},
            {"parts": [{"from": 5, "to": 1}]},
        ]
        r = await post_cut(cuts_env, preset="cut-demo")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "unit" in doc["error"] or "overlap" in doc["error"]
        job = (await cuts_env.client.get(f"/v1/jobs/{doc['job_id']}")).json()
        assert job["state"] == "failed"

    async def test_keep_guards_refuse_to_apply(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=40)
        cuts_env.llm.cut_answer = {"parts": [{"from": 1, "to": 2}], "summary": "s", "kept_s": 10}
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "remove almost everything" in doc["error"]

    async def test_highlights_skip_the_guard(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=40)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 2, "label": "Best"}],
            "summary": "s",
            "kept_s": 10,
        }
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready"

    async def test_highlights_keep_the_target_length(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=132)  # 11 min, one unit per 5 s
        # 22 parts of 30 s (all 11 min), ranked backwards: the last part matters most.
        cuts_env.llm.cut_answer = {
            "parts": [
                {"from": i * 6 + 1, "to": i * 6 + 6, "label": f"P{i}", "rank": 22 - i}
                for i in range(22)
            ],
            "summary": "s",
            "kept_s": 660,
        }
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        cut = doc["cut"]
        assert cut["target_s"] == 300
        assert 255 <= cut["kept_s"] <= 345 and cut["kept_ms"] == int(cut["kept_s"] * 1000)
        starts = [p["start_ms"] for p in cut["parts"]]
        assert starts == sorted(starts)
        # The most important parts (the last ones) are in, the least important (the first) out.
        assert cut["parts"][-1]["end_ms"] >= 655_000
        assert cut["parts"][0]["start_ms"] > 300_000
        assert len(cuts_env.llm.cut_calls) == 1
        assert "Target length: 300 s" in cuts_env.llm.cut_calls[0]

    async def test_old_format_answer_without_ranks_still_builds(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=132)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": i * 6 + 1, "to": i * 6 + 6, "label": f"P{i}"} for i in range(22)],
            "summary": "s",
            "kept_s": 660,
        }
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert 255 <= doc["cut"]["kept_s"] <= 345
        assert doc["cut"]["parts"][0]["label"] == "P0"

    async def test_answer_far_below_the_band_is_retried_once_with_the_length(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=132)
        short = {"parts": [{"from": 1, "to": 6, "label": "A", "rank": 1}], "summary": "s"}
        long = {
            "parts": [
                {"from": i * 6 + 1, "to": i * 6 + 6, "label": f"P{i}", "rank": i + 1}
                for i in range(12)
            ],
            "summary": "s",
        }
        cuts_env.llm.cut_answers = [short, long]
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready", doc
        assert 255 <= doc["cut"]["kept_s"] <= 345
        assert len(cuts_env.llm.cut_calls) == 2

    async def test_still_short_after_the_retry_is_a_clear_error(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=132)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 6, "label": "A", "rank": 1}],
            "summary": "s",
        }
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "300 s" in doc["error"] and len(cuts_env.llm.cut_calls) == 2

    async def test_typed_prompt_has_no_target(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=132)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 6, "label": "A"}, {"from": 20, "to": 40, "label": "B"}],
            "summary": "s",
        }
        r = await post_cut(cuts_env, prompt="Keep the first minute and a bit")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready" and doc["cut"]["target_s"] is None
        assert "Target length" not in cuts_env.llm.cut_calls[0]

    async def test_unknown_preset_and_bad_bodies(self, cuts_env):
        r = await post_cut(cuts_env, preset="cut-nope")
        assert r.status_code == 409
        r = await post_cut(cuts_env)
        assert r.status_code == 409
        r = await post_cut(cuts_env, prompt="   ")
        assert r.status_code == 409
        r = await post_cut(cuts_env, preset="cut-demo", await_prompt=True)
        assert r.status_code == 409
        r = await post_cut(cuts_env, preset="cut-demo", prompt="both at once")
        assert r.status_code == 400


class TestAwaitPrompt:
    async def test_wait_then_fill_then_build(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        r = await post_cut(cuts_env, await_prompt=True)
        body = r.json()
        assert body["state"] == "waiting"
        rid = body["request_id"]
        doc = (await cuts_env.client.get(f"/v1/cuts/{rid}")).json()
        assert doc["state"] == "waiting"
        r = await cuts_env.client.put(f"/v1/cut-requests/{rid}", json={"prompt": "Just the ending"})
        assert r.status_code == 200 and r.json()["state"] == "building"
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 5, "to": 6, "label": "Ending"}],
            "summary": "s",
            "kept_s": 10,
        }
        doc = await wait_ready(cuts_env, rid)
        assert doc["state"] == "ready" and doc["instruction"] == "Just the ending"

    async def test_fill_rejects_empty_and_unknown(self, cuts_env):
        r = await post_cut(cuts_env, await_prompt=True)
        rid = r.json()["request_id"]
        r = await cuts_env.client.put(f"/v1/cut-requests/{rid}", json={"prompt": "  "})
        assert r.status_code == 409
        r = await cuts_env.client.put("/v1/cut-requests/nope", json={"prompt": "x"})
        assert r.status_code == 404
        r = await cuts_env.client.put(f"/v1/cut-requests/{rid}", json={"prompt": "Now build it"})
        assert r.status_code == 200
        cuts_env.llm.cut_answer = {"parts": [{"from": 1, "to": 1}], "summary": "s", "kept_s": 5}
        await wait_ready(cuts_env, rid)
        r = await cuts_env.client.put(f"/v1/cut-requests/{rid}", json={"prompt": "again"})
        assert r.status_code == 409

    async def test_another_user_cannot_fill_or_see(self, cuts_env):
        r = await post_cut(cuts_env, await_prompt=True)
        rid = r.json()["request_id"]
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        assert (await partner.get(f"/v1/cuts/{rid}")).status_code == 404
        assert (
            await partner.put(f"/v1/cut-requests/{rid}", json={"prompt": "hijack"})
        ).status_code == 404
        assert (await partner.delete(f"/v1/cut-requests/{rid}")).status_code == 404

    async def test_queue_orders_and_hides_dismissed(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        # A build that fails deterministically (both repair rounds answer with bad ids).
        cuts_env.llm.cut_answers = [{"parts": [{"from": 99, "to": 100}]}] * 2
        failed = (await post_cut(cuts_env, prompt="Cut the chatter")).json()["request_id"]
        await wait_ready(cuts_env, failed)
        cuts_env.llm.cut_answer = {"parts": [{"from": 1, "to": 2}], "summary": "s", "kept_s": 10}
        ready = (await post_cut(cuts_env, preset="cut-demo")).json()["request_id"]
        await wait_ready(cuts_env, ready)
        waiting = (await post_cut(cuts_env, await_prompt=True)).json()["request_id"]
        q = (await env_queue(cuts_env)).json()["requests"]
        assert [c["state"] for c in q] == ["waiting", "ready", "failed"]
        assert all(c["title"] for c in q), "a card never shows a bare id"
        r = await cuts_env.client.delete(f"/v1/cut-requests/{waiting}")
        assert r.json() == {"ok": True}
        q = (await env_queue(cuts_env)).json()["requests"]
        assert waiting not in [c["id"] for c in q]
        assert [c["state"] for c in q] == ["ready", "failed"]


class TestTranscriptPath:
    async def test_needs_transcript_then_ready_after_asr(self, cuts_env):
        cuts_env.fetcher.text = None  # no captions at all
        cuts_env.cfg.cuts.min_keep_frac = 0.0  # the ASR transcript is short; accept its keep
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 1, "to": 1, "label": "All"}],
            "summary": "s",
            "kept_s": 4,
        }
        r = await post_cut(cuts_env, preset="cut-no-filler")
        rid = r.json()["request_id"]
        doc = (await cuts_env.client.get(f"/v1/cuts/{rid}")).json()
        assert doc["state"] in ("needs_transcript", "building")
        # The ASR chain (a real ffmpeg spawn) is slow on a loaded host; the long poll caps at
        # wait_ms_cap, so poll again until the build ends instead of assuming one call is enough.
        for _ in range(30):
            doc = await wait_ready(cuts_env, rid, wait_ms=15000)
            if doc["state"] in ("ready", "failed"):
                break
        assert doc["state"] == "ready"
        # The ASR transcript arrived through the transcript job; its unit came from the audio.
        assert doc["cut"]["transcript_hash"]

    async def test_untranscribable_video_fails_with_a_plain_reason(self, cuts_env):
        cuts_env.fetcher.error = YoutubeVideoError("private")
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=15000)
        assert doc["state"] == "failed"
        assert "transcript" in doc["error"].lower()

    async def test_transcript_without_timings_is_refused(self, cuts_env):
        cuts_env.fetcher.segments = None  # the default transcript has no timed rows
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed"
        assert "timings" in doc["error"]

    async def test_live_video_is_refused(self, cuts_env):
        cuts_env.fetcher.text = None  # no transcript: the live check runs before any fetch
        r = await cuts_env.client.post(
            f"/v1/videos/{VID}/cuts",
            params={"is_live": "true"},
            json={"preset": "cut-no-filler"},
        )
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "live" in doc["error"].lower()


class TestCapsAndConfig:
    async def test_per_user_cap_on_concurrent_builds(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.delay_s = 0.2
        cuts_env.cfg.cuts.max_active_per_user = 1
        first = (await post_cut(cuts_env, preset="cut-demo")).json()
        second = await post_cut(cuts_env, preset="cut-no-filler")
        assert second.status_code == 429
        cuts_env.llm.delay_s = 0.0
        await wait_ready(cuts_env, first["request_id"])

    async def test_not_configured_reports_plainly(self, env):
        env.cfg.cuts.poll_s = 0.02
        r = await env.client.post(f"/v1/videos/{VID}/cuts", json={"preset": "cut-demo"})
        assert r.status_code == 409 and "not configured" in r.json()["error"]
        state = (await env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert state["configured"] is False and state["presets"]
        me = (await env.client.get("/v1/me")).json()
        assert me["features"]["cuts"] is False

    async def test_features_flag_follows_config(self, cuts_env):
        me = (await cuts_env.client.get("/v1/me")).json()
        assert me["features"]["cuts"] is True

    async def test_too_long_transcript_is_refused(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.cfg.cuts.max_input_tokens = 100
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "too long" in doc["error"]

    async def test_dismiss_while_building_stops_the_job(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.delay_s = 0.2
        rid = (await post_cut(cuts_env, preset="cut-demo")).json()["request_id"]
        r = await cuts_env.client.delete(f"/v1/cut-requests/{rid}")
        assert r.status_code == 200
        await cuts_env.client.get(f"/v1/cuts/{rid}")
        doc = (await cuts_env.client.get(f"/v1/cuts/{rid}")).json()
        assert doc["state"] == "dismissed"
        job = (await cuts_env.client.get(f"/v1/jobs/{doc['job_id']}")).json()
        assert job["state"] == "cancelled"

    async def test_long_poll_returns_when_ready(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        rid = (await post_cut(cuts_env, preset="cut-demo")).json()["request_id"]
        cuts_env.llm.cut_answer = {"parts": [{"from": 1, "to": 3}], "summary": "s", "kept_s": 15}
        doc = await wait_ready(cuts_env, rid)
        assert doc["state"] == "ready"

    async def test_long_poll_times_out_building(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.delay_s = 10.0
        rid = (await post_cut(cuts_env, preset="cut-demo")).json()["request_id"]
        doc = await wait_ready(cuts_env, rid, wait_ms=100)
        assert doc["state"] == "building"
        await cuts_env.client.delete(f"/v1/cut-requests/{rid}")

    async def test_wait_defaults_to_the_configured_wait(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.delay_s = 0.5
        cuts_env.cfg.cuts.default_wait_ms = 400
        rid = (await post_cut(cuts_env, preset="cut-demo")).json()["request_id"]
        started = time.monotonic()
        doc = (await cuts_env.client.get(f"/v1/cuts/{rid}")).json()
        waited = time.monotonic() - started
        assert doc["state"] == "building" and 0.3 < waited < 2.5
        await cuts_env.client.delete(f"/v1/cut-requests/{rid}")

    async def test_a_cut_preset_cannot_run_as_a_summary(self, cuts_env):
        r = await cuts_env.client.get(
            f"/v1/videos/{VID}/summary", params={"prompt": "builtin/cut-no-filler"}
        )
        assert r.status_code == 400 and "cut preset" in r.json()["error"]


class TestSavedPresets:
    async def test_a_saved_preset_is_a_chip_and_builds_under_its_name(self, cuts_env):
        set_transcript(cuts_env.fetcher)
        cuts_env.llm.cut_answer = {
            "parts": [{"from": 2, "to": 4, "label": "Dessert"}],
            "summary": "s",
            "kept_s": 15,
        }
        saved = await cuts_env.client.post(
            "/v1/cut-presets", json={"label": "Dessert only", "prompt": "Keep only the dessert."}
        )
        assert saved.status_code == 200, saved.text
        preset = saved.json()["preset"]
        assert preset["label"] == "Dessert only" and preset["id"].startswith("cut-mine-")
        listing = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert any(
            p["id"] == preset["id"] and p["label"] == "Dessert only" for p in listing["presets"]
        )
        rid = (await post_cut(cuts_env, preset=preset["id"])).json()["request_id"]
        doc = await wait_ready(cuts_env, rid)
        assert doc["state"] == "ready"
        # The label the owner saved rides along with the built cut (not the id).
        assert doc["cut"]["label"] == "Dessert only"
        assert doc["cut"]["preset_id"] == preset["id"]

    async def test_the_same_name_and_description_replace_not_duplicate(self, cuts_env):
        body = {"label": "Dessert only", "prompt": "Keep only the dessert."}
        first = (await cuts_env.client.post("/v1/cut-presets", json=body)).json()["preset"]
        second = (await cuts_env.client.post("/v1/cut-presets", json=body)).json()["preset"]
        assert first["id"] == second["id"]
        own = (await cuts_env.client.get("/v1/cut-presets")).json()["presets"]
        assert [p["id"] for p in own] == [first["id"]]

    async def test_saved_presets_belong_to_their_owner_and_delete(self, cuts_env):
        made = (
            await cuts_env.client.post(
                "/v1/cut-presets", json={"label": "Mine", "prompt": "Keep the demo."}
            )
        ).json()["preset"]
        partner = httpx_client(cuts_env, OTHER_TOKEN)
        assert (await partner.get("/v1/cut-presets")).json()["presets"] == []
        assert (await partner.delete(f"/v1/cut-presets/{made['id']}")).status_code == 404
        assert (await cuts_env.client.delete(f"/v1/cut-presets/{made['id']}")).status_code == 200
        # The last saved preset deletes the set, so the built-ins are all that remain.
        assert (await cuts_env.client.get("/v1/cut-presets")).json()["presets"] == []
        listing = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert all(not p["id"].startswith("cut-mine-") for p in listing["presets"])

    async def test_a_builtin_preset_cannot_be_deleted_from_the_saved_list(self, cuts_env):
        r = await cuts_env.client.delete("/v1/cut-presets/cut-no-filler")
        assert r.status_code == 404
        listing = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert any(p["id"] == "cut-no-filler" for p in listing["presets"])

    async def test_saved_presets_need_a_name_and_a_description(self, cuts_env):
        for body in (
            {"label": "", "prompt": "Keep the demo."},
            {"label": "Name", "prompt": ""},
            {"label": "Name", "prompt": " "},
        ):
            r = await cuts_env.client.post("/v1/cut-presets", json=body)
            assert r.status_code == 400, (body, r.text)

    async def test_cut_presets_stay_out_of_the_summary_prompt_lists(self, cuts_env):
        await cuts_env.client.post(
            "/v1/cut-presets", json={"label": "Mine", "prompt": "Keep the demo."}
        )
        listing = (await cuts_env.client.get("/v1/prompts")).json()
        assert all(s["id"] != "cut-presets" for s in listing["sets"])
        for pset in listing["sets"]:
            assert all(not key.endswith("cut-mine") for key in [p["key"] for p in pset["prompts"]])

    async def test_the_saved_list_has_a_cap(self, cuts_env):
        import utubot.prompts as prompts_mod

        old = prompts_mod.MAX_CUT_PRESETS
        prompts_mod.MAX_CUT_PRESETS = 2
        try:
            await cuts_env.client.post("/v1/cut-presets", json={"label": "One", "prompt": "A."})
            await cuts_env.client.post("/v1/cut-presets", json={"label": "Two", "prompt": "B."})
            r = await cuts_env.client.post(
                "/v1/cut-presets", json={"label": "Three", "prompt": "C."}
            )
            assert r.status_code == 400 and "delete one" in r.text
            again = await cuts_env.client.post(
                "/v1/cut-presets", json={"label": "One", "prompt": "A."}
            )
            assert again.status_code == 200
        finally:
            prompts_mod.MAX_CUT_PRESETS = old


def httpx_client(env, token: str):
    import httpx

    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


def env_queue(env):
    return env.client.get("/v1/cut-requests")
