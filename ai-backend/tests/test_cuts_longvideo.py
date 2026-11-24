"""Director's cuts of long videos: map over excerpts, reduce over candidates (GitHub #95)."""

from __future__ import annotations

import re

import pytest

from tests.test_cuts_api import VID, post_cut, set_transcript, wait_ready
from utubot.config import LLMTask


@pytest.fixture
async def cuts_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


UNIT_LINE = re.compile(r"^#(\d+) \[[^\]]+\] ", re.MULTILINE)
CANDIDATE_LINE = re.compile(
    r"^#(\d+) \[[^\]]+\] .*?\(rank (\d+) of (\d+) in its excerpt\)", re.MULTILINE
)
EXCERPT = re.compile(r"excerpt (\d+) of (\d+)")
BLOCK = 6  # units per proposed candidate
THREE_HOURS_S = 3 * 3600
UNIT_S = 10.0


class LongVideoModel:
    """A stand-in model for the cut route: an excerpt proposes every third block of six units,
    the reduce keeps every candidate in the order of its rank. `broken` maps an excerpt number to
    how many of its answers are garbage."""

    def __init__(self):
        self.broken: dict[int, int] = {}
        self.maps: list[tuple[int, int, str]] = []
        self.reduces: list[str] = []

    def __call__(self, system: str, user: str):
        if "You finish director's cuts" in system:
            return self.reduce(user)
        return self.map(user)

    def map(self, user: str):
        i, n = (int(x) for x in EXCERPT.search(user).groups())
        self.maps.append((i, n, user))
        if self.broken.get(i, 0) > 0:
            self.broken[i] -= 1
            return {"nope": True}
        ids = [int(m) for m in UNIT_LINE.findall(user)]
        blocks = sorted({(u - 1) // BLOCK for u in ids if ((u - 1) // BLOCK) % 3 == 0})
        order = sorted(blocks, key=lambda b: (b * 7) % 11)
        parts = []
        for block in blocks:
            inside = [u for u in ids if (u - 1) // BLOCK == block]
            parts.append(
                {
                    "from": inside[0],
                    "to": inside[-1],
                    "label": f"Block {block}",
                    "rank": order.index(block) + 1,
                }
            )
        return {"parts": parts, "summary": f"excerpt {i}", "kept_s": 0}

    def reduce(self, user: str):
        self.reduces.append(user)
        rows = [(int(a), int(r) / int(m)) for a, r, m in CANDIDATE_LINE.findall(user)]
        order = sorted(rows, key=lambda row: (row[1], row[0]))
        rank = {cid: pos + 1 for pos, (cid, _) in enumerate(order)}
        parts = [
            {"from": cid, "to": cid, "label": f"Pick {cid}", "rank": rank[cid]}
            for cid, _ in sorted(rows)
        ]
        return {"parts": parts, "summary": "Long video cut.", "kept_s": 0}


def three_hours(env, *, chunk_tokens: int = 3000, max_tokens: int = 6000):
    set_transcript(env.fetcher, n=int(THREE_HOURS_S / UNIT_S), seconds_each=UNIT_S)
    cuts = env.cfg.cuts
    cuts.max_input_tokens = max_tokens
    cuts.map_chunk_tokens = chunk_tokens
    cuts.map_overlap_units = 3
    cuts.reduce_excerpt_chars = 40
    model = LongVideoModel()
    env.llm.cut_answer = model
    return model


async def events_of(env, doc):
    job = (await env.client.get(f"/v1/jobs/{doc['job_id']}")).json()
    return job["events"]


class TestLongVideos:
    async def test_a_three_hour_video_is_cut_to_the_target_band(self, cuts_env):
        model = three_hours(cuts_env)
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        assert doc["state"] == "ready", doc
        cut = doc["cut"]
        assert cut["target_s"] == 300
        assert 255 <= cut["kept_s"] <= 345, cut["kept_s"]
        assert cut["duration_ms"] == int(THREE_HOURS_S * 1000)
        starts = [p["start_ms"] for p in cut["parts"]]
        assert starts == sorted(starts)
        assert len(model.maps) >= 4 and len(model.reduces) == 1
        # Every excerpt was asked for its share of the target, the reduce for all of it.
        assert all("kept from this excerpt" in user for _, _, user in model.maps)
        assert "Target length: 300 s kept in total" in model.reduces[0]
        events = await events_of(cuts_env, doc)
        stages = [e["stage"] for e in events]
        assert "map" in stages and "reduce" in stages and "model" not in stages
        progress = [e["detail"] for e in events if e["stage"] == "map" and "done" in e["detail"]]
        assert progress[-1]["done"] == progress[-1]["of"] == len(model.maps)

    async def test_excerpts_overlap_and_the_overlap_is_not_cut_twice(self, cuts_env):
        model = three_hours(cuts_env)
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        seen = [
            [int(u) for u in UNIT_LINE.findall(user)]
            for _, _, user in sorted(model.maps, key=lambda m: m[0])
        ]
        for before, after in zip(seen, seen[1:], strict=False):
            assert set(before) & set(after), "neighbouring excerpts share units"
        every = [u for ids in seen for u in ids]
        assert set(every) == set(range(1, int(THREE_HOURS_S / UNIT_S) + 1))
        # The reduce lists each candidate once: ids in the reduce call are 1..n without repeats.
        ids = [int(a) for a, _, _ in CANDIDATE_LINE.findall(model.reduces[0])]
        assert ids == list(range(1, len(ids) + 1))

    async def test_a_typed_prompt_keeps_its_meaning(self, cuts_env):
        model = three_hours(cuts_env)
        prompt = "Only the parts about sourdough starters"
        r = await post_cut(cuts_env, prompt=prompt)
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        assert doc["state"] == "ready", doc
        assert doc["cut"]["target_s"] is None
        assert all(f"Task: {prompt}" in user for _, _, user in model.maps)
        assert all("Target length" not in user for _, _, user in model.maps)
        assert f"Task: {prompt}" in model.reduces[0]
        assert "give every part a rank" in model.maps[0][2]

    async def test_a_video_that_fits_stays_one_pass(self, cuts_env):
        set_transcript(cuts_env.fetcher, n=30)
        cuts_env.llm.cut_answer = {"parts": [{"from": 1, "to": 12}], "summary": "s", "kept_s": 60}
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "ready"
        assert len(cuts_env.llm.cut_calls) == 1
        stages = [e["stage"] for e in await events_of(cuts_env, doc)]
        assert "model" in stages and "map" not in stages and "reduce" not in stages

    async def test_one_failed_excerpt_is_retried_once(self, cuts_env):
        model = three_hours(cuts_env)
        model.broken = {2: 2}  # the answer and its repair are garbage; the retry works
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        assert doc["state"] == "ready", doc
        assert sum(1 for i, _, _ in model.maps if i == 2) == 3
        events = await events_of(cuts_env, doc)
        warned = [e["detail"] for e in events if e["stage"] == "map" and e["status"] == "warn"]
        assert any(w.get("excerpt") == 2 and w.get("retry") == 1 for w in warned)

    async def test_an_excerpt_that_keeps_failing_fails_the_cut_with_a_reason(self, cuts_env):
        model = three_hours(cuts_env)
        model.broken = {2: 99}
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        assert doc["state"] == "failed"
        assert doc["error"].startswith("Part 2 of ") and "no cut was built" in doc["error"]
        assert (
            sum(1 for i, _, _ in model.maps if i == 2) == 4
        )  # two tries, each an answer and its repair

    async def test_candidates_over_the_budget_are_reduced_in_rounds(self, cuts_env):
        model = three_hours(cuts_env, chunk_tokens=1000, max_tokens=1300)
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=30000)
        assert doc["state"] == "ready", doc
        assert 255 <= doc["cut"]["kept_s"] <= 345
        events = await events_of(cuts_env, doc)
        rounds = [
            e["detail"] for e in events if e["stage"] == "reduce" and e["detail"].get("round")
        ]
        assert rounds, "the candidates needed a narrowing round"
        final = [e for e in events if e["stage"] == "reduce" and "rounds" in e["detail"]][-1]
        assert final["detail"]["rounds"] >= 1
        # Every request stayed inside the model's input budget.
        limit = cuts_env.cfg.cuts.max_input_tokens * cuts_env.cfg.cuts.chars_per_token
        assert all(len(user) <= limit for user in cuts_env.llm.cut_calls)
        assert len(model.reduces) > 2  # the groups of the round plus the final call

    async def test_too_many_candidates_fail_clearly_when_rounds_run_out(self, cuts_env):
        three_hours(cuts_env, chunk_tokens=1000, max_tokens=1300)
        cuts_env.cfg.cuts.max_reduce_rounds = 1
        cuts_env.cfg.cuts.reduce_excerpt_chars = 200
        r = await post_cut(cuts_env, prompt="Every demonstration")
        doc = await wait_ready(cuts_env, r.json()["request_id"], wait_ms=30000)
        assert doc["state"] == "failed"
        assert "candidate" in doc["error"]

    async def test_a_unit_that_cannot_fit_one_request_is_refused(self, cuts_env):
        three_hours(cuts_env)
        cuts_env.cfg.cuts.max_input_tokens = 100
        r = await post_cut(cuts_env, preset="cut-no-filler")
        doc = await wait_ready(cuts_env, r.json()["request_id"])
        assert doc["state"] == "failed" and "too long" in doc["error"]

    async def test_progress_rides_on_the_request_while_the_map_runs(self, cuts_env):
        three_hours(cuts_env)
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        rid = r.json()["request_id"]
        doc = await wait_ready(cuts_env, rid, wait_ms=20000)
        job_id = doc["job_id"]
        cuts = cuts_env.svc.cuts
        cuts.jobs.events.record(job_id, "map", "running", {"done": 3, "of": 9})
        assert cuts._last_stage(job_id) == "map"
        assert cuts._last_progress(job_id) == {"done": 3, "of": 9}
        cuts.jobs.events.record(job_id, "reduce", "running", {"candidates": 5})
        assert cuts._last_progress(job_id) is None

    async def test_a_ready_highlights_cut_shows_in_the_picker_for_a_long_video(self, cuts_env):
        three_hours(cuts_env)
        r = await post_cut(cuts_env, preset="cut-highlights-5")
        await wait_ready(cuts_env, r.json()["request_id"], wait_ms=20000)
        state = (await cuts_env.client.get(f"/v1/videos/{VID}/cuts")).json()
        entry = next(p for p in state["presets"] if p["id"] == "cut-highlights-5")
        assert entry["state"] == "ready" and entry["cut"]["target_s"] == 300

    async def test_a_repeat_request_reuses_the_stored_long_cut(self, cuts_env):
        model = three_hours(cuts_env)
        first = await post_cut(cuts_env, preset="cut-highlights-5")
        await wait_ready(cuts_env, first.json()["request_id"], wait_ms=20000)
        calls = len(model.maps) + len(model.reduces)
        second = await post_cut(cuts_env, preset="cut-highlights-5")
        doc = await wait_ready(cuts_env, second.json()["request_id"])
        assert doc["state"] == "ready"
        assert len(model.maps) + len(model.reduces) == calls
