from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from utubot.assess import TRIAGE_SYSTEM, topics_hash
from utubot.models import VideoMeta

EVAL_PATH = Path(__file__).parent.parent / "eval" / "assess_clickbait.json"

# The old prompt judged clickbait from the title/thumbnail text alone, with no channel, genre or
# subscription context. It is the "before" the eval set measures.
OLD_CLICKBAIT_PHRASES = (
    "shocking",
    "they hide",
    "weird trick",
    "gone wrong",
    "exposed",
    "you won't believe",
    "big reveal",
)


def old_clickbait_score(title: str) -> bool:
    score = 0.1
    for phrase in OLD_CLICKBAIT_PHRASES:
        if phrase in title.lower():
            score = max(score, 0.85)
    if re.findall(r"\b[A-Z]{3,}\b", title):
        score = max(score, 0.7)
    return score >= 0.6


def load_eval() -> list[dict]:
    return json.loads(EVAL_PATH.read_text())["cases"]


def to_meta(case: dict) -> VideoMeta:
    fields = {
        "video_id": case["video_id"],
        "title": case["title"],
        "channel": case["channel"],
        "channel_id": case.get("channel_id"),
        "is_subscribed": case.get("is_subscribed"),
        "subscriber_count": case.get("subscriber_count"),
        "channel_description": case.get("channel_description"),
        "channel_titles": case.get("channel_titles"),
        "views": case.get("views"),
        "likes": case.get("likes"),
        "dislikes": case.get("dislikes"),
        "upload_date": case.get("upload_date"),
        "duration_s": case.get("duration_s"),
        "description": case.get("description"),
    }
    return VideoMeta(**{k: v for k, v in fields.items() if v is not None or k == "video_id"})


async def _assess_one(env, case: dict):
    meta = to_meta(case)
    r = await env.client.post("/v1/assess", json={"videos": [meta.model_dump()], "wait_ms": 2000})
    assert r.status_code == 200
    return r.json()["results"][0]


async def _verdicts_for_all(env, cases: list[dict]):
    metas = [to_meta(case) for case in cases]
    r = await env.client.post(
        "/v1/assess", json={"videos": [m.model_dump() for m in metas], "wait_ms": 2000}
    )
    assert r.status_code == 200
    return r.json()["results"]


async def test_triage_prompt_defines_clickbait_as_context_aware():
    text = TRIAGE_SYSTEM.lower()
    for needle in (
        "out-of-the-ordinary",
        "subscribes to",
        "regular show",
        "comedy",
        "satirical",
        "lower the score",
    ):
        assert needle in text, needle


async def test_triage_payload_carries_channel_and_video_context(env):
    case = next(c for c in load_eval() if c["video_id"] == "jimmycarr01")
    await _assess_one(env, case)
    calls = [c for c in env.llm.calls if "triage YouTube videos" in c["messages"][0]["content"]]
    assert len(calls) == 1
    payload = json.loads(calls[0]["messages"][1]["content"].split("Videos: ", 1)[1])[0]
    # Every context field is built into the prompt's payload, so none is left out by accident.
    for field in (
        "channel_id",
        "subscriber_count",
        "channel_description",
        "is_subscribed",
        "likes",
        "dislikes",
        "upload_date",
        "channel_titles",
    ):
        assert field in payload, field
    # The signals that undo a punchy headline on a regular show are actually present for this case.
    for field in ("channel_description", "is_subscribed", "subscriber_count", "channel_titles"):
        assert payload[field] is not None, field


async def test_eval_verdicts_match_expected_labels(env):
    cases = load_eval()
    verdicts = await _verdicts_for_all(env, cases)
    wrong = [
        (c["video_id"], c["expected"], v["action"])
        for c, v in zip(cases, verdicts, strict=True)
        if (v["action"] in ("mark", "hide")) != (c["expected"] == "clickbait")
    ]
    assert not wrong, f"after: {wrong}"


async def test_eval_measures_before_and_after(env):
    cases = load_eval()
    before_wrong = []
    for case in cases:
        if old_clickbait_score(case["title"]) != (case["expected"] == "clickbait"):
            before_wrong.append(case["video_id"])
    # The old title-only labeling misjudged at least the Jimmy Carr regular show.
    assert "jimmycarr01" in before_wrong, before_wrong

    env.llm.legacy_clickbait = True
    for case in cases:
        if case["video_id"] in before_wrong:
            verdict = await _assess_one(env, case)
            # The legacy prompt, fed the same title, would have flagged it.
            assert verdict["action"] in ("mark", "hide"), (case["video_id"], verdict["action"])

    # Drop the legacy-labeled triage and its tier-2 deep analysis so the context-aware pass
    # re-runs the whole pipeline from the model.
    env.svc.db.execute("DELETE FROM triage")
    env.svc.db.execute("DELETE FROM deep")
    env.llm.legacy_clickbait = False
    verdicts = await _verdicts_for_all(env, cases)
    wrong = [
        c["video_id"]
        for c, v in zip(cases, verdicts, strict=True)
        if (v["action"] in ("mark", "hide")) != (c["expected"] == "clickbait")
    ]
    assert not wrong, f"after: {wrong}"


async def test_subscribed_comedy_shows_are_not_clickbait(env):
    for case in load_eval():
        if case["video_id"] in ("jimmycarr01", "jimmycarr02", "jimmycarr03"):
            verdict = await _assess_one(env, case)
            assert verdict["action"] == "none", (case["title"], verdict["action"])


async def test_genuine_deception_still_flagged_on_subscribed_non_comedy(env):
    for case in load_eval():
        if case["video_id"] in ("financevid0", "cookingvid0"):
            verdict = await _assess_one(env, case)
            assert verdict["action"] in ("mark", "hide"), (case["title"], verdict["action"])


async def test_reassess_subscribed_corrects_a_wrong_label(env):
    jimmy = next(c for c in load_eval() if c["video_id"] == "jimmycarr01")

    # A wrong label from the old prompt: the legacy answer flags the subscribed comedy show.
    env.llm.legacy_clickbait = True
    seeded = await _assess_one(env, jimmy)
    assert seeded["action"] in ("mark", "hide"), seeded["action"]

    # Re-assessing the user's recent clickbait verdicts on subscribed channels re-triages with the
    # context-aware prompt and clears the wrong one.
    env.llm.legacy_clickbait = False
    n = await env.svc.assessor.reassess_subscribed("owner", env.cfg.users[0].policy)
    assert n == 1

    reassessed = await _assess_one(env, jimmy)
    assert reassessed["action"] == "none", reassessed["action"]
    assert not any(f["kind"] == "clickbait" for f in reassessed.get("flags", []))


async def test_reassess_noop_when_no_subscribed_clickbait(env):
    await env.client.post(
        "/v1/assess",
        json={"videos": [to_meta(load_eval()[1]).model_dump()], "wait_ms": 2000},
    )
    n = await env.svc.assessor.reassess_subscribed("owner", env.cfg.users[0].policy)
    assert n == 0


async def test_triage_from_the_old_prompt_is_not_reused(env):
    topics = [*env.cfg.users[0].policy.hide_topics, *env.cfg.users[0].policy.mark_topics]
    legacy = hashlib.sha256(json.dumps(sorted(topics)).encode()).hexdigest()[:16]
    assert topics_hash(topics) != legacy


async def test_triage_gets_the_channels_usual_titles_from_stored_meta(env):
    jimmy = next(c for c in load_eval() if c["video_id"] == "jimmycarr01")
    env.svc.transcripts.store_meta(
        "olderepisode", {"channel_id": jimmy["channel_id"], "title": "Older regular episode"}
    )
    meta = VideoMeta(video_id=jimmy["video_id"], channel_id=jimmy["channel_id"])

    assert env.svc.assessor._recent_channel_titles(meta) == ["Older regular episode"]
    assert env.svc.assessor._recent_channel_titles(VideoMeta(video_id="x")) is None
