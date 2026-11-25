"""The offline release gate for caption tracks (pure functions, file reading).

Two `utubot captions-score` reports are compared: the candidate (the track the backend makes) and
the baseline (YouTube's automatic captions, or another engine's track). The candidate ships only
when it is no worse on sync and clearly better on meaning. Meaning comes from a recorded
evaluation in the reports (`meaning: {score, passed, reference}`), never from a live model here.

`captions-gate --attestation` writes the result; a backend with `[captions] gate_required = true`
and `gate_attestation` pointing at it refuses to store caption tracks while it is missing or has
not passed. The numbers are `captions.gate_*` in the config so a fixture with a different
character (a slow drama, a dense panel) can tighten them without code changes.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..config import CaptionsConfig

DIGITS = 3
GATE_VERSION = 1


def _seconds(report: dict[str, Any], key: str) -> float | None:
    value = (report.get("overall") or {}).get(key)
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def compare(
    candidate: dict[str, Any], baseline: dict[str, Any], cfg: CaptionsConfig
) -> dict[str, Any]:
    """Compare two score reports; the result names every failed check."""
    c = candidate.get("overall") or {}
    b = baseline.get("overall") or {}
    failures: list[str] = []
    hit = float(c.get("hit") or 0.0)
    base_hit = float(b.get("hit") or 0.0)
    loose = float(c.get("loose") or 0.0)
    base_loose = float(b.get("loose") or 0.0)
    median = _seconds(candidate, "median_s")
    base_median = _seconds(baseline, "median_s")
    p95 = _seconds(candidate, "p95_s")
    base_p95 = _seconds(baseline, "p95_s")
    if hit < cfg.gate_hit_min:
        failures.append(f"hit {hit:.3f} is under {cfg.gate_hit_min:.3f}")
    if hit < base_hit + cfg.gate_hit_margin:
        failures.append(
            f"hit {hit:.3f} is not {cfg.gate_hit_margin:.3f} over the baseline {base_hit:.3f}"
        )
    if loose < base_loose:
        failures.append(f"loose {loose:.3f} is below the baseline {base_loose:.3f}")
    if loose < cfg.gate_loose_min:
        failures.append(f"loose {loose:.3f} is under {cfg.gate_loose_min:.3f}")
    if median is None or base_median is None:
        failures.append("median offset was not measured for both tracks")
    else:
        if abs(median) > cfg.gate_median_max_s:
            failures.append(
                f"median offset {abs(median):.3f} s is over {cfg.gate_median_max_s:.3f} s"
            )
        if abs(median) > abs(base_median):
            failures.append(
                f"median offset {abs(median):.3f} s is worse than the baseline {abs(base_median):.3f} s"
            )
    if p95 is None or base_p95 is None:
        failures.append("p95 offset was not measured for both tracks")
    else:
        if abs(p95) > cfg.gate_p95_max_s:
            failures.append(f"p95 offset {abs(p95):.3f} s is over {cfg.gate_p95_max_s:.3f} s")
        if abs(p95) > abs(base_p95):
            failures.append(
                f"p95 offset {abs(p95):.3f} s is worse than the baseline {abs(base_p95):.3f} s"
            )
    words = (candidate.get("words") or {}).get("within_s")
    if words is None:
        failures.append("the candidate has no word times to measure")
    elif float(words) < cfg.gate_words_within_min:
        failures.append(f"word within {float(words):.3f} is under {cfg.gate_words_within_min:.3f}")
    short = int((candidate.get("track") or {}).get("short_cues") or 0)
    if short > cfg.gate_max_short_cues:
        failures.append(f"{short} cues are under {cfg.gate_short_cue_s:.1f} s")
    meaning = (candidate.get("meaning") or {}).get("score")
    base_meaning = (baseline.get("meaning") or {}).get("score")
    candidate_passed = (candidate.get("meaning") or {}).get("passed")
    if meaning is None or base_meaning is None:
        failures.append("meaning was not measured for both tracks")
    else:
        if candidate_passed is False:
            failures.append(
                f"meaning {float(meaning):.3f} is under the {cfg.gate_meaning_min:.3f} floor"
            )
        elif float(meaning) < cfg.gate_meaning_min:
            failures.append(
                f"meaning {float(meaning):.3f} is under the {cfg.gate_meaning_min:.3f} floor"
            )
        if float(meaning) <= float(base_meaning):
            failures.append(
                f"meaning {float(meaning):.3f} does not beat the baseline {float(base_meaning):.3f}"
            )
    return {
        "version": GATE_VERSION,
        "passed": not failures,
        "failures": failures,
        "candidate": {
            "hit": round(hit, DIGITS),
            "loose": round(loose, DIGITS),
            "median_s": None if median is None else round(median, DIGITS),
            "p95_s": None if p95 is None else round(p95, DIGITS),
            "words_within": None if words is None else round(float(words), DIGITS),
            "short_cues": short,
            "meaning": None if meaning is None else round(float(meaning), DIGITS),
        },
        "baseline": {
            "hit": round(base_hit, DIGITS),
            "loose": round(base_loose, DIGITS),
            "median_s": None if base_median is None else round(base_median, DIGITS),
            "p95_s": None if base_p95 is None else round(base_p95, DIGITS),
            "meaning": None if base_meaning is None else round(float(base_meaning), DIGITS),
        },
    }


def write_attestation(path: str | Path, result: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def check_attestation(path: str | Path | None) -> str | None:
    """Why the release gate has not passed, or None when its attestation is current and passed."""
    if not path:
        return "no gate attestation is configured"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"the gate attestation cannot be read ({exc})"
    if data.get("version") != GATE_VERSION:
        return "the gate attestation was made by another gate version"
    if data.get("passed") is not True:
        return "the last gate run did not pass"
    return None
