"""The offline release gate for caption tracks (pure functions).

Two `utubot captions-score` reports are compared: the candidate (the track the backend makes) and
the baseline (YouTube's automatic captions, or another engine's track). The candidate ships only
when it is not worse on sync and is better on meaning. Meaning comes from a recorded evaluation
(`meaning: {"score": ..., "passed": ...}`), never from a live model here: this module reads JSON.

The numbers are `captions.gate_*` in the config so a fixture with a different character (a slow
drama, a dense panel) can tighten them without code changes.
"""

from __future__ import annotations

from typing import Any

from ..config import CaptionsConfig

DIGITS = 3


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
    if meaning is None or base_meaning is None:
        failures.append("meaning was not measured for both tracks")
    elif float(meaning) < float(base_meaning):
        failures.append(
            f"meaning {float(meaning):.3f} is below the baseline {float(base_meaning):.3f}"
        )
    return {
        "passed": not failures,
        "failures": failures,
        "candidate": {
            "hit": round(hit, DIGITS),
            "loose": round(loose, DIGITS),
            "words_within": None if words is None else round(float(words), DIGITS),
            "short_cues": short,
            "meaning": None if meaning is None else round(float(meaning), DIGITS),
        },
        "baseline": {
            "hit": round(base_hit, DIGITS),
            "loose": round(base_loose, DIGITS),
            "meaning": None if base_meaning is None else round(float(base_meaning), DIGITS),
        },
    }
