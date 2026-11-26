from __future__ import annotations

import pytest

from utubot.config import CutsConfig, LLMTask
from utubot.cuts import CUT_SKIM_FILM_PRESET_ID, build_units, effective_target_s
from utubot.prompts import BUILTIN_SET, CUT_PRESET_INSTRUCTIONS

VID = "abcdefghijk"
CFG = CutsConfig()
SKIM = "skim-film"  # the preset's instruction key; its id is cut-skim-film


def film_segs(n: int = 200, seconds_each: float = 5.0):
    """A film-length timed transcript: `n` beats, matching the metadata duration below."""
    segs = []
    at = 0.0
    for i in range(n):
        segs.append((at, at + seconds_each / 2, f"Beat {i} first part"))
        segs.append((at + seconds_each / 2, at + seconds_each, f"Beat {i} second part."))
        at += seconds_each
    return segs, int(at)


def ranked_parts(units_per_part: int = 10, count: int = 20):
    # `count` parts of `units_per_part` units: they must fit the transcript's unit count.
    return {
        "parts": [
            {
                "from": i * units_per_part + 1,
                "to": (i + 1) * units_per_part,
                "label": f"P{i}",
                "rank": count - i,
            }
            for i in range(count)
        ],
        "summary": "A skim of the film.",
    }


# ---- the preset itself ------------------------------------------------------------------------


class TestSkimFilmPreset:
    def test_is_a_builtin_cut_preset_with_the_scene_instruction(self):
        presets = [p for p in BUILTIN_SET.prompts if p.task == "cuts"]
        ids = [p.id for p in presets]
        assert CUT_SKIM_FILM_PRESET_ID in ids
        skim = next(p for p in presets if p.id == CUT_SKIM_FILM_PRESET_ID)
        # No description is needed: the preset infers the story from the scenes itself.
        assert "skim the film" in skim.label.lower()
        text = CUT_PRESET_INSTRUCTIONS[SKIM].lower()
        assert "scene" in text and "story" in text
        assert "mid-shot" in text or "mid-sentence" in text

    def test_it_targets_a_fraction_of_the_runtime(self):
        # A film-length cut keeps a fraction of the runtime; here about half.
        assert CFG.preset_target_frac[CUT_SKIM_FILM_PRESET_ID] == 0.5
        film = 81 * 60
        assert effective_target_s(CFG, CUT_SKIM_FILM_PRESET_ID, film) == film // 2

    def test_build_units_yields_the_scene_beats_the_preset_keeps_from(self):
        # The preset cuts at scene/sentence boundaries: each beat is its own unit.
        segs, _duration = film_segs(n=200)
        assert len(build_units(segs, CFG)) == 200


class TestFractionValidation:
    def test_a_fraction_out_of_range_is_rejected(self):
        with pytest.raises(ValueError):
            CutsConfig(preset_target_frac={CUT_SKIM_FILM_PRESET_ID: 1.0})
        with pytest.raises(ValueError):
            CutsConfig(preset_target_frac={CUT_SKIM_FILM_PRESET_ID: 0.0})


# ---- the build --------------------------------------------------------------------------------


async def _cut_env(env):
    env.cfg.llm.cuts = LLMTask(model="cutmodel")
    env.cfg.cuts.poll_s = 0.02
    env.cfg.cuts.transcript_wait_s = 60.0
    env.cfg.cuts.wait_ms_cap = 3000
    env.cfg.cuts.default_wait_ms = 0
    env.cfg.captions.job_poll_s = 0.02
    return env


async def post(env, **body):
    return await env.client.post(f"/v1/videos/{VID}/cuts", json=body)


async def wait_ready(env, request_id, *, wait_ms: int = 5000):
    r = await env.client.get(f"/v1/cuts/{request_id}", params={"wait_ms": wait_ms})
    return r.json()


class TestSkimFilmBuild:
    async def test_builds_the_film_to_half_its_length(self, env):
        env = await _cut_env(env)
        segs, duration = film_segs(n=200)  # 1000 s -> target about 500 s
        env.fetcher.segments = segs
        env.fetcher.meta_extra = {"duration_s": duration}
        env.llm.cut_answer = ranked_parts()

        r = await post(env, preset=CUT_SKIM_FILM_PRESET_ID)
        assert r.status_code == 200, r.text
        doc = await wait_ready(env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        # The target is half the film; the cut lands in the accepted band around it.
        assert doc["cut"]["target_s"] == 500
        assert 425 <= doc["cut"]["kept_s"] <= 575
        # The model was told the target length, so it gave every part a rank.
        assert "Target length: 500 s" in env.llm.cut_calls[0]

    async def test_uses_an_asr_transcript_when_captions_are_poor_or_missing(self, env):
        # Films often have poor or missing captions: the cut is built from a Whisper (ASR)
        # transcript when the audio download works, exactly like a caption transcript.
        env = await _cut_env(env)
        segs, duration = film_segs(n=200)
        env.fetcher.meta_extra = {"duration_s": duration}
        env.svc.transcripts.store_asr(VID, "film transcript", "en", segments=segs)
        env.llm.cut_answer = ranked_parts()

        r = await post(env, preset=CUT_SKIM_FILM_PRESET_ID)
        doc = await wait_ready(env, r.json()["request_id"])
        assert doc["state"] == "ready", doc.get("error")
        # The cut was built from the Whisper (ASR) transcript, not captions.
        assert env.svc.transcripts.cached(VID).source == "asr"
        assert doc["cut"]["target_s"] == 500

    async def test_is_offered_like_the_other_built_in_presets(self, env):
        env = await _cut_env(env)
        segs, _duration = film_segs(n=4)
        env.fetcher.segments = segs
        env.fetcher.meta_extra = {"duration_s": 20}
        doc = (await env.client.get(f"/v1/videos/{VID}/cuts")).json()
        assert CUT_SKIM_FILM_PRESET_ID in [p["id"] for p in doc["presets"]]
