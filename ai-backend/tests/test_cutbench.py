from __future__ import annotations

import json
import re

from utubot.config import CutsConfig
from utubot.cutbench import (
    LONG_TRANSCRIPT,
    TRANSCRIPTS,
    BenchRequest,
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
    def test_five_transcripts_with_three_or_more_requests_each(self):
        assert len(TRANSCRIPTS) == 5
        for transcript in TRANSCRIPTS:
            assert len(transcript.requests) >= 3
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
    def test_the_model_message_carries_the_fixture_chapters(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        units = build_units(transcript.segments, CFG)
        by_start = sorted(units, key=lambda u: u.start)
        parts = []
        for a, b in request.keep:
            first = next(u.n for u in by_start if u.start >= a - 0.01)
            last = next(u.n for u in reversed(by_start) if u.end <= b + 0.01)
            parts.append((first, last))
        calls: list = []
        score_request(transcript, request, fake_model(answer(parts), calls=calls), "fake")
        message = calls[0][1]["content"]
        assert "Chapters:" in message
        assert "- 00:00 Intro" in message

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

    def test_an_invalid_range_answer_gets_the_engine_repair_round(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        units = build_units(transcript.segments, CFG)
        by_start = sorted(units, key=lambda u: u.start)
        parts = []
        for a, b in request.keep:
            first = next(u.n for u in by_start if u.start >= a - 0.01)
            last = next(u.n for u in reversed(by_start) if u.end <= b + 0.01)
            parts.append((first, last))
        calls: list = []

        def model_fn(messages):
            calls.append(messages)
            if len(calls) == 1:
                return answer([(0, 2)]), {}
            return answer(parts), {}

        result = score_request(transcript, request, model_fn, "fake")
        assert result.format_error is None, result.row()
        assert result.repairs == 1
        assert len(calls) == 2
        assert "Your previous answer was rejected" in calls[1][-1]["content"]
        assert result.keep > 0.9, result.row()

    def test_a_second_bad_ids_answer_reports_the_ids_problem(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        calls: list = []

        def model_fn(messages):
            calls.append(messages)
            return answer([(0, 2)]), {}

        result = score_request(transcript, request, model_fn, "fake")
        assert result.format_error is not None
        assert result.format_error.startswith("part 1 names units 0-2; the transcript has")
        assert result.repairs == 1
        assert len(calls) == 2

    def test_two_unparsable_answers_are_a_format_error_not_a_crash(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        calls: list = []

        def model_fn(messages):
            calls.append(messages)
            return "not json at all", {}

        result = score_request(transcript, request, model_fn, "fake")
        assert result.format_error == "the answer was not the JSON object"
        assert result.repairs == 1
        assert len(calls) == 2
        assert result.score == 0.0

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
        # the unparsable answer is retried, then the empty parts answer gets the range repair
        assert result.format_error and result.repairs == 2
        assert len(calls) == 3
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
        assert summary["requests"] == 16
        assert summary["format_errors"] == 0
        assert summary["mean_keep"] > 0.6


class TestLengthAccuracy:
    def test_a_targeted_request_reports_how_far_the_length_is_from_the_target(self):
        transcript = TRANSCRIPTS[0]
        units = build_units(transcript.segments, CFG)
        request = BenchRequest(
            name="short",
            instruction="Keep the highlights.",
            preset_id=None,
            keep=[(units[0].start, units[-1].end)],
            skip=[],
            target_s=60,
        )
        # Ranked parts worth ~110 s: the server cuts them down to the 60 s target.
        rows, at = [], 0.0
        for u in units:
            if at > 110:
                break
            rows.append({"from": u.n, "to": u.n, "rank": len(rows) + 1})
            at += u.end - u.start
        text = json.dumps({"parts": rows, "summary": "s", "kept_s": 110})
        result = score_request(transcript, request, fake_model(text), "m")
        assert result.target_s == 60
        assert result.length_err is not None and result.length_err <= CFG.length_tolerance
        assert summarize([result])["mean_length_err"] == result.length_err

    def test_requests_without_a_target_have_no_length_number(self):
        transcript = TRANSCRIPTS[0]
        request = transcript.requests[0]
        result = score_request(transcript, request, fake_model(answer([(1, 2)])), "m")
        assert result.length_err is None
        assert summarize([result])["mean_length_err"] is None


UNIT_ROW = re.compile(r"^#(\d+) \[[^\]]+\] (.*)$", re.MULTILINE)
CANDIDATE_ROW = re.compile(r"^#(\d+) \[", re.MULTILINE)


def long_video_model(calls: list):
    """A model that proposes the "decisive" lines of an excerpt and keeps every candidate."""

    def model_fn(messages):
        calls.append(messages)
        system, user = messages[0]["content"], messages[1]["content"]
        if "You finish director's cuts" in system:
            ids = [int(i) for i in CANDIDATE_ROW.findall(user)]
            parts = [{"from": i, "to": i, "rank": n + 1} for n, i in enumerate(ids)]
        else:
            hits = [int(n) for n, text in UNIT_ROW.findall(user) if "decisive" in text]
            parts = [{"from": hits[0], "to": hits[-1], "rank": 1}] if hits else []
        return json.dumps({"parts": parts, "summary": "s", "kept_s": 0}), {"prompt_tokens": 7}

    return model_fn


class TestLongVideo:
    def test_the_fixture_is_three_hours_and_needs_map_reduce(self):
        assert 2.5 * 3600 < LONG_TRANSCRIPT.duration_s < 3.5 * 3600
        assert LONG_TRANSCRIPT not in TRANSCRIPTS
        assert LONG_TRANSCRIPT.cuts_overrides["max_input_tokens"] < CFG.max_input_tokens
        assert {r.name for r in LONG_TRANSCRIPT.requests} == {"decisive-steps", "highlights-5min"}

    def test_the_long_case_runs_by_map_reduce_and_scores(self):
        calls: list = []
        results = [
            score_request(LONG_TRANSCRIPT, request, long_video_model(calls), "fake")
            for request in LONG_TRANSCRIPT.requests
        ]
        for result in results:
            assert result.refused is None and result.format_error is None, result.row()
            assert result.skip == 1.0 and result.prompt_tokens > 0, result.row()
        assert results[0].keep > 0.9, results[0].row()
        assert len(calls) > 2 * 5  # several excerpts and a reduce per request
        assert any("You finish director's cuts" in c[0]["content"] for c in calls)
        target = next(r for r in results if r.request == "highlights-5min")
        assert target.target_s == 300 and target.length_err <= CFG.length_tolerance + 0.05
        assert target.keep > 0.2

    def test_a_dead_model_refuses_the_long_case_instead_of_raising(self):
        request = LONG_TRANSCRIPT.requests[0]
        result = score_request(LONG_TRANSCRIPT, request, fake_model("no json here"), "fake")
        assert result.refused and "Part 1" in result.refused
