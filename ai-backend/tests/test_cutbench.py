from __future__ import annotations

import json

from utubot.config import CutsConfig
from utubot.cutbench import (
    TRANSCRIPTS,
    score_request,
    summarize,
)
from utubot.cuts import build_units

CFG = CutsConfig()


def answer(parts: list[tuple[int, int]], labels: list[str] | None = None) -> str:
    """A model answer in the engine's wire format."""
    return json.dumps(
        {
            "parts": [
                {
                    "from": a,
                    "to": b,
                    "label": (labels or ["part"])[i]
                    if labels and i < len(labels)
                    else f"Part {i + 1}",
                }
                for i, (a, b) in enumerate(parts)
            ],
            "summary": "test summary",
            "kept_s": 60,
        }
    )


def fake_model(answer_text: str, *, usage: dict | None = None, calls: list | None = None):
    def model_fn(messages):
        if calls is not None:
            calls.append(messages)
        return answer_text, usage or {"prompt_tokens": 10, "completion_tokens": 5}

    return model_fn


class TestFixtures:
    def test_five_transcripts_with_three_requests_each(self):
        assert len(TRANSCRIPTS) == 5
        for transcript in TRANSCRIPTS:
            assert len(transcript.requests) == 3
            assert transcript.duration_s > 60
            assert transcript.segments and transcript.segments[0][0] == 0

    def test_segments_are_caption_like_and_monotonic(self):
        for transcript in TRANSCRIPTS:
            previous_end = -1.0
            for start, end, text in transcript.segments:
                assert 0 < end - start <= 20, (transcript.id, text)
                assert start >= previous_end - 0.001, (transcript.id, text)
                assert text.strip()
                previous_end = end

    def test_marks_live_inside_the_video_and_do_not_overlap_within_a_kind(self):
        for transcript in TRANSCRIPTS:
            for request in transcript.requests:
                for kind in ("keep", "skip"):
                    spans = sorted(getattr(request, kind))
                    for (_, b), (a2, _) in zip(spans, spans[1:], strict=False):
                        assert b <= a2, (transcript.id, request.name, kind)
                    for a, b in spans:
                        assert 0 <= a < b <= transcript.duration_s + 0.01
                assert request.keep and request.skip
                assert request.instruction.strip()

    def test_units_form_for_every_fixture(self):
        for transcript in TRANSCRIPTS:
            units = build_units(transcript.segments, CFG)
            assert 10 <= len(units) <= 200, (transcript.id, len(units))


class TestScorer:
    def test_a_perfect_answer_scores_full(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        units = build_units(transcript.segments, CFG)
        by_start = sorted(units, key=lambda u: u.start)
        parts = []
        for a, b in request.keep:
            first = next(u.n for u in by_start if u.start >= a - 0.01)
            last = next(u.n for u in reversed(by_start) if u.end <= b + 0.01)
            parts.append((first, last))
        result = score_request(transcript, request, fake_model(answer(parts)), "fake")
        assert result.refused is None and result.format_error is None
        assert result.keep > 0.9, result.row()
        assert result.skip > 0.95, result.row()
        assert result.score > 0.85

    def test_keeping_a_must_skip_span_is_punished(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        units = build_units(transcript.segments, CFG)
        # keep the sponsor block (a must-skip) instead of the substance
        sponsor = request.skip[1]
        by_start = sorted(units, key=lambda u: u.start)
        first = next(u.n for u in by_start if u.start >= sponsor[0] - 0.01)
        last = next(u.n for u in reversed(by_start) if u.end <= sponsor[1] + 0.01)
        result = score_request(transcript, request, fake_model(answer([(first, last)])), "fake")
        assert result.keep < 0.2
        assert result.skip < 0.7  # only the sponsor range leaks; the marked intro/outro stay clean
        assert result.score < 0

    def test_keeping_the_whole_video_is_diluted_by_the_budget(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[1]  # just-the-answer: a short budget
        units = build_units(transcript.segments, CFG)
        # keep every unit except a slice at the end (the 95% guard would refuse more)
        result = score_request(
            transcript, request, fake_model(answer([(1, len(units) - 2)])), "fake"
        )
        assert result.keep == 1.0  # the marked verdict is covered
        assert result.excess > 0.3  # but nearly the whole video survived
        assert result.score < 0

    def test_format_failure_after_repair_scores_zero(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[1]
        calls: list = []

        def model_fn(messages):
            calls.append(messages)
            if len(calls) == 1:
                return "not json at all", {}
            return '{"parts": [], "summary": "x", "kept_s": 1}', {}

        result = score_request(transcript, request, model_fn, "fake")
        assert result.format_error and result.repairs == 1
        assert len(calls) == 2
        assert result.score == 0.0

    def test_score_all_runs_the_whole_set(self):
        transcript = TRANSCRIPTS[1]
        request = transcript.requests[0]
        units = build_units(transcript.segments, CFG)
        by_start = sorted(units, key=lambda u: u.start)
        parts = []
        for a, b in request.keep:
            first = next(u.n for u in by_start if u.start >= a - 0.01)
            last = next(u.n for u in reversed(by_start) if u.end <= b + 0.01)
            parts.append((first, last))
        good = fake_model(answer(parts))
        results = []
        for transcript in TRANSCRIPTS:
            for request in transcript.requests:
                results.append(score_request(transcript, request, good, "perfect-ish"))
        summary = summarize(results)
        assert summary["requests"] == 15
        assert summary["format_errors"] == 0
        assert summary["mean_keep"] > 0.6
