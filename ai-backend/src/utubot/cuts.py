"""Director's cuts: a model picks which parts of a video to keep, the TV skips the rest.

A cut request (preset or a prompt the owner typed) runs as its own async task: it makes sure a
timed transcript exists, merges the caption fragments into sentence-like units, asks the
`[llm.cuts]` model for the unit ranges to keep, validates and repairs the answer, and stores the
finished cut under a cache key shared by every user. The job row and its events are only the
report; the queue the phone shows is the `cut_requests` table.
"""

from __future__ import annotations

import asyncio
import bisect
import hashlib
import json
import logging
import math
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .captions import events
from .captions.jobs import JobQueue
from .config import Config, CutsConfig, LLMTask
from .db import (
    MAX_CHANNEL_ID_CHARS,
    MAX_CHANNEL_NAME_CHARS,
    MODE_RULE_CHANNEL,
    MODE_RULE_REQUEST,
    MODE_RULE_SERVER,
    MODE_RULE_USER,
    Database,
)
from .llm import INTERACTIVE, LLMClient, LLMError
from .prompts import CUT_PRESET_INSTRUCTIONS, Prompt, PromptStore
from .transcripts import SOURCE_ASR, Transcript, TranscriptService, fmt_ts

log = logging.getLogger("utubot.cuts")

# Stages this feature writes into the job report (the captions pipeline writes the others).
STAGE_TRANSCRIPT = "transcript"
STAGE_MODEL = "model"
STAGE_CHECKING = "checking"
STAGE_MAP = "map"  # long videos: excerpt i of n (detail `done`, `of`)
STAGE_REDUCE = "reduce"  # long videos: the final choice over the candidates (detail `round`)

REQUEST_STATES = ("waiting", "building", "needs_transcript", "ready", "failed", "dismissed")
BUILDING_STATES = ("building", "needs_transcript")
QUEUE_LIMIT = 100
CUT_DOC_VERSION = 1

# A sentence end in caption text: one of these characters ends a unit early.
SENTENCE_END = ".!?…？！。"
CHAPTER_RE = re.compile(
    r"^\s*[\[(]?((?:\d{1,2}:)?\d{1,2}:\d{2})[\])]?\s+(.{2,100})\s*$", re.MULTILINE
)
MAX_CHAPTERS = 40
UNITS_MARK = "Transcript units (each line starts with its id and time range):"
CUT_JSON_RULES = (
    "Remember the rules: reply with the JSON object only; ids are the unit numbers you were "
    "given; from <= to; ranges never overlap and stay in video order; every id must exist."
)
MAP_RETRIES = 1  # a failed excerpt is asked once more, then the cut fails
CANDIDATES_MARK = "Candidate parts (each line starts with its id and time range):"
PRESET_LABELS = {
    "cut-no-filler": "No filler",
    "cut-answer": "Just the answer",
    "cut-demo": "Only the demo",
    "cut-highlights-5": "Highlights in 5 min",
}
# Removal presets keep whatever the video has left worth keeping; keeping nearly all of it is a
# valid result ("little or no filler"), so only the lower keep guard applies to them.
REMOVAL_PRESET_IDS = frozenset({"cut-no-filler", "cut-answer", "cut-demo"})
NO_FILLER_PRESET_ID = "cut-no-filler"


def cut_clock(ms: int) -> str:
    """Milliseconds as the clients show a length: `1:12`, or `1:02:03` past an hour."""
    seconds = max(0, int(round(ms / 1000.0)))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def removal_summary(
    preset_id: str | None, parts: list[Part], duration_s: float | None, fallback: str
) -> str:
    """The one-line result of a removal preset: what it removed, or that there was nothing to."""
    if preset_id not in REMOVAL_PRESET_IDS or not duration_s:
        return fallback
    duration_ms = int(duration_s * 1000)
    kept_ms = sum(p.end_ms - p.start_ms for p in parts)
    removed_ms = max(0, duration_ms - kept_ms)
    if removed_ms <= 0:
        return "No filler found" if preset_id == NO_FILLER_PRESET_ID else "Nothing was removed"
    percent = max(1, round(removed_ms / duration_ms * 100))
    if preset_id == NO_FILLER_PRESET_ID:
        return f"Removed {cut_clock(removed_ms)} of filler, {percent} % of the video"
    return f"Removed {cut_clock(removed_ms)}, {percent} % of the video"


MODE_LABELS = {"quick": "Quick", "watched": "Watched"}
WATCHED_REASON = "Watched cuts are not configured on this server."


@dataclass(frozen=True)
class SourceRef:
    """What a cut is built from: a YouTube video, or another release (scheme:id:season)."""

    kind: str
    key: str
    release_key: str | None = None
    release_duration_ms: int | None = None

    def as_doc(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind, "key": self.key}
        if self.release_key is not None:
            out["release_key"] = self.release_key
        if self.release_duration_ms is not None:
            out["release_duration_ms"] = self.release_duration_ms
        return out


def watched_available(cfg: Config | None = None) -> bool:  # noqa: ARG001 (cp1 has no vision model)
    """Watched cuts need `[llm.cuts_vision]`; until checkpoint 3/4 the answer is always no."""
    return False


def source_ref(row: Any) -> SourceRef:
    """The source columns of a request or cut row; null columns mean the YouTube video.

    This is the only reader of `source_kind`/`source_key`/`release_*`, so a missing column
    raises here instead of leaking into the cut logic.
    """
    kind = row["source_kind"] or "youtube"
    key = row["source_key"]
    if not key:
        key = f"{kind}:{row['video_id']}"
    return SourceRef(kind, key, row["release_key"], row["release_duration_ms"])


def source_matches(left: SourceRef, right: SourceRef, tolerance_ms: int) -> bool:
    """Same source and release, and a length within the configured tolerance."""
    if left.key != right.key:
        return False
    if left.release_key or right.release_key:
        if left.release_key != right.release_key:
            return False
    if left.release_duration_ms is not None and right.release_duration_ms is not None:
        if abs(left.release_duration_ms - right.release_duration_ms) > tolerance_ms:
            return False
    return True


CUT_SYSTEM = (
    "You build director's cuts of YouTube videos for a TV viewer: you choose which numbered "
    "transcript units to keep so the video plays the way the task asks. Reply ONLY with JSON: "
    '{"parts":[{"from":<int>,"to":<int>,"label":"<2-6 words>"}],'
    '"summary":"<one line, at most 120 characters>","kept_s":<int>}. '
    '"from" and "to" are the first and last unit id of one kept part. Ranges never overlap, ids '
    "must exist, and parts stay in video order. When the task gives a target length, add "
    '"rank":<int> to every part (1 = the most important part, every part its own number). '
    "Be faithful to the transcript; never invent "
    "content and never add commentary."
)

REDUCE_SYSTEM = (
    "You finish director's cuts of long YouTube videos for a TV viewer. The video was read in "
    "excerpts and each excerpt proposed candidate parts; you choose which numbered candidates "
    "to keep so the video plays the way the task asks. Reply ONLY with JSON: "
    '{"parts":[{"from":<int>,"to":<int>,"label":"<2-6 words>"}],'
    '"summary":"<one line, at most 120 characters>","kept_s":<int>}. '
    'Every part is ONE candidate: "from" and "to" are the same candidate id. Ids must exist and '
    "parts stay in video order. When the task gives a target length, add "
    '"rank":<int> to every part (1 = the most important part, every part its own number). '
    "Each candidate shows its rank inside its own excerpt; ranks of different excerpts are not "
    "comparable, so judge by the label and the text. Be faithful to the candidates; never "
    "invent content and never add commentary."
)
MAP_NOTE = (
    "This is excerpt {i} of {n} of a long video that is read in pieces; neighbouring excerpts "
    "share a few units. Propose candidate parts from THIS excerpt only, with the unit ids as "
    "given. A later step makes the final choice across the whole video, so propose every part "
    "that fits the task, give every part a rank (1 = the best fit for the task in this "
    'excerpt, every part its own number) and answer {{"parts":[]}} when nothing here fits.'
)
REDUCE_NOTE = (
    "The video is long, so it was read in excerpts. The lines below are CANDIDATE parts the "
    "excerpts proposed, not transcript units: each shows its id, time range, label, its rank "
    "inside its own excerpt and a short text excerpt. Choose the candidates to keep; each part "
    "you return is one candidate (from and to are the same id)."
)


class CutRefused(RuntimeError):
    """The cut cannot be built or applied; `message` is the plain reason shown to the owner."""

    def __init__(self, message: str, *, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


class CutFormatError(ValueError):
    """The model's answer breaks the cut rules; carries the reason for the repair round."""

    def __init__(self, problem: str):
        super().__init__(problem)
        self.problem = problem


@dataclass
class Unit:
    """One sentence-like unit the model chooses from: `#n [start-end] text`."""

    n: int
    start: float
    end: float
    text: str


@dataclass
class Part:
    """One kept part of a finished cut, in milliseconds."""

    label: str
    start_ms: int
    end_ms: int
    rank: int | None = None  # 1 = most important; None when the model gave none
    first: int | None = None  # first and last unit id the part was built from
    last: int | None = None


def _clean_text(text: str) -> str:
    return " ".join(text.split())


def _effective_end(index: int, segments: list[tuple[float, float, str]]) -> float:
    """A segment with no duration ends where the next one begins (timedtext json3 rows)."""
    start, end, _ = segments[index]
    if end > start:
        return end
    return segments[index + 1][0] if index + 1 < len(segments) else start


def build_units(segments: list[tuple[float, float, str]], cfg) -> list[Unit]:
    """Merge caption fragments into sentence-like units: a new unit starts on a pause over
    `cuts.unit_max_pause_s` or after sentence punctuation, and a unit never grows past
    `cuts.unit_max_s`."""
    max_pause = cfg.unit_max_pause_s
    max_len = cfg.unit_max_s
    units: list[Unit] = []
    start: float | None = None
    end = 0.0
    parts: list[str] = []

    def flush() -> None:
        nonlocal start, parts
        if parts and start is not None:
            units.append(Unit(len(units) + 1, start, end, " ".join(parts)))
        start, parts = None, []

    prev_end: float | None = None
    prev_text = ""
    for index, (seg_start, _seg_end, raw) in enumerate(segments):
        text = _clean_text(raw)
        if not text:
            continue
        seg_end = _effective_end(index, segments)
        pause = 0.0 if prev_end is None else seg_start - prev_end
        too_long = start is not None and seg_end - start > max_len
        if parts and (pause > max_pause or too_long or prev_text.endswith(tuple(SENTENCE_END))):
            flush()
        if seg_end - seg_start > max_len:
            # One caption block longer than the cap is split across its own length, evenly by time.
            words = text.split()
            chunks = max(1, round((seg_end - seg_start) / max_len))
            size = max(1, len(words) // chunks)
            for i in range(chunks):
                chunk = (
                    " ".join(words[i * size : (i + 1) * size])
                    if i < chunks - 1
                    else " ".join(words[i * size :])
                )
                if not chunk:
                    continue
                if start is not None:
                    flush()
                at = seg_start + (seg_end - seg_start) * i / chunks
                until = seg_start + (seg_end - seg_start) * (i + 1) / chunks
                units.append(Unit(len(units) + 1, at, until, chunk))
                start, end, prev_text = None, until, chunk
            prev_end = seg_end
            continue
        if start is None:
            start = seg_start
        end = max(seg_end, start)
        parts.append(text)
        prev_end = max(seg_end, prev_end or 0.0)
        prev_text = text
    flush()
    return units


def parse_chapters(description: str | None) -> list[tuple[float, str]]:
    """`(seconds, title)` chapters from a YouTube description, in order, duplicate stamps dropped."""
    if not description:
        return []
    out: list[tuple[float, str]] = []
    seen: set[float] = set()
    for stamp, title in CHAPTER_RE.findall(description):
        seconds = 0.0
        for bit in stamp.split(":"):
            seconds = seconds * 60 + int(bit)
        title = _clean_text(title)
        if not title or seconds in seen:
            continue
        seen.add(seconds)
        out.append((seconds, title[:100]))
    out.sort()
    return out[:MAX_CHAPTERS]


def transcript_hash(segments: list[tuple[float, float, str]]) -> str:
    blob = json.dumps([[round(s, 3), round(e, 3), t] for s, e, t in segments], ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def unit_line(u: Unit) -> str:
    return f"#{u.n} [{fmt_ts(u.start)}-{fmt_ts(u.end)}] {u.text}"


def serialize_units(
    units: list[Unit],
    chapters: list[tuple[float, str]],
    meta: dict[str, Any],
    instruction: str,
    target_s: int | None = None,
    over_ask_frac: float = 0.0,
    *,
    note: str | None = None,
    scope: str = "in total",
    mark: str = UNITS_MARK,
) -> str:
    """The user message the cut model answers: the video facts, the task, then the numbered units.

    `note` is an extra paragraph after the task (map/reduce says which excerpt this is), `scope`
    what the target length counts ("in total", or "from this excerpt"), `mark` the line that
    introduces the numbered lines."""
    duration = meta.get("duration_s")
    lines = [
        f"Title: {meta.get('title') or ''}",
        f"Channel: {meta.get('channel') or ''}",
        f"Duration: {fmt_ts(duration) if duration else 'unknown'}"
        + (f" ({int(duration)} s)" if duration else ""),
    ]
    if chapters:
        lines.append("Chapters:")
        lines.extend(f"- {fmt_ts(at)} {title}" for at, title in chapters)
    lines.append(f"Task: {instruction.strip()}")
    if note:
        lines.append(note)
    if target_s:
        ask_s = int(target_s * (1 + over_ask_frac))
        lines.append(
            f"Target length: {target_s} s kept {scope}. Keep a little more than that, about "
            f"{ask_s} s of unit time, and give every part a rank (1 = most important): the "
            "server drops the lowest-ranked parts until the target fits."
        )
    lines.append(mark)
    lines.extend(unit_line(u) for u in units)
    lines.append("Answer with the JSON object the system message describes.")
    return "\n".join(lines)


def parse_cut_answer(data: Any, units: list[Unit], *, allow_empty: bool = False) -> list[Part]:
    """The model's JSON answer as kept parts, or `CutFormatError` naming the problem.

    `units` is the list the model saw: the whole transcript, or one excerpt (consecutive units
    that keep their transcript ids). `allow_empty` accepts `"parts": []` (an excerpt with
    nothing to propose)."""
    if not isinstance(data, dict):
        raise CutFormatError("the answer is not a JSON object")
    raw_parts = data.get("parts")
    if not isinstance(raw_parts, list) or (not raw_parts and not allow_empty):
        raise CutFormatError("'parts' is missing or empty")
    lo, hi = units[0].n, units[-1].n
    last_to = lo - 1
    out: list[Part] = []
    for i, raw in enumerate(raw_parts):
        if not isinstance(raw, dict):
            raise CutFormatError(f"part {i + 1} is not an object")
        try:
            start_n = int(raw["from"])
            end_n = int(raw["to"])
        except (KeyError, TypeError, ValueError):
            raise CutFormatError(f"part {i + 1} has no valid from/to unit ids") from None
        if not lo <= start_n <= end_n <= hi:
            raise CutFormatError(
                f"part {i + 1} names units {start_n}-{end_n}; the transcript has {lo}-{hi}"
            )
        if start_n <= last_to:
            raise CutFormatError(f"part {i + 1} overlaps or goes before part {i}")
        label = _clean_text(str(raw.get("label") or ""))[:80]
        try:
            rank = int(raw["rank"])
        except (KeyError, TypeError, ValueError):
            rank = None  # the old format has no rank: parts count in video order
        out.append(
            Part(
                label or f"Part {i + 1}",
                int(units[start_n - lo].start * 1000),
                int(units[end_n - lo].end * 1000),
                rank,
                start_n,
                end_n,
            )
        )
        last_to = end_n
    return out


def target_band(target_s: int, tolerance: float) -> tuple[float, float]:
    """The accepted kept length (s) around a preset's target: `(low, high)`."""
    return target_s * (1 - tolerance), target_s * (1 + tolerance)


# ---- length intent ------------------------------------------------------------------------------

MIN_TARGET_S = 30
BUILTIN_CUT_IDS = frozenset(f"cut-{name}" for name in CUT_PRESET_INSTRUCTIONS)
LENGTH_SECONDS = "s"
LENGTH_FRACTION = "frac"
_SHRINK = r"(?:shorter|shorten|trim|reduce|remove|drop|cut|shave)"
_NUM = r"(\d+(?:\.\d+)?)"
_FRACTIONS = {
    "half": 0.5,
    "third": 1 / 3,
    "quarter": 0.25,
    "two thirds": 2 / 3,
    "three quarters": 0.75,
}
_FRACTION_WORDS = "|".join(sorted(_FRACTIONS, key=len, reverse=True))
# A portion of the video named by position ("the first half") is not a length.
_POSITION = frozenset(
    {
        "first",
        "last",
        "second",
        "final",
        "middle",
        "opening",
        "closing",
        "latter",
        "other",
        "same",
        "than",
    }
)
_NOT_A_LENGTH = {
    "first", "last", "skip", "skipping", "after", "before", "from", "until", "at", "past",
    "remove", "removing", "drop", "dropping", "minute", "second", "next",
}  # fmt: skip


_CUES = frozenset(
    {"keep", "cut", "make", "shorten", "shorter", "trim", "reduce", "to", "down", "most", "under",
     "about", "around", "roughly", "within", "length", "long", "short", "version"}
)  # fmt: skip
_LENGTH_TAIL = re.compile(
    r"\s*(?:of (?:it|the video)\b|as long\b|long\b|version\b|shorter\b|total\b)"
)
_AFTER_CUE = frozenset({"of", "as", "it", "long", "please", "total", "version", "or", "and", "in"})


def _has_length_context(low: str, start: int, end: int) -> bool:
    """A number or fraction word names a length only as the whole prompt, with a length phrase
    after it, or after a length verb and followed by nothing that makes it part of a title."""
    lead, tail = low[:start].strip(" .,!?:;"), low[end:]
    if not lead and not tail.strip(" .,!?:;"):
        return True
    if _LENGTH_TAIL.match(tail):
        return True
    if _CUES & set(re.findall(r"[a-z']+", lead)[-3:]):
        following = re.findall(r"[a-z0-9']+", tail)[:1]
        return not following or following[0] in _AFTER_CUE
    return False


def _fraction_matches(text: str) -> set[float]:
    found: set[float] = set()
    removing = re.compile(
        rf"{_SHRINK}\s+(?:it\s+)?(?:down\s+)?by\s+(?:a\s+|one\s+)?({_FRACTION_WORDS})s?\b"
    )
    spans = []
    for m in removing.finditer(text):
        found.add(1 - _FRACTIONS[m.group(1)])
        spans.append(m.span(1))
    kept = re.compile(
        rf"\b(?:a\s+|one\s+)?({_FRACTION_WORDS})s?\b(?!\s+(?:an?\s+)?(?:hour|minute))"
    )
    for m in kept.finditer(text):
        if any(a <= m.start(1) < b for a, b in spans):
            continue
        before = text[: m.start()].split()[-1:]
        if before and before[0] in _POSITION:
            continue
        if not _has_length_context(text, m.start(), m.end()):
            continue
        found.add(_FRACTIONS[m.group(1)])
    return found


def parse_length_intent(text: str) -> tuple[str, float] | None:
    """The length an English description asks for: `("frac", kept fraction)` or `("s", seconds)`.
    None when it names no length, or names several or an unclear one (then no target is used)."""
    low = (text or "").lower()
    found: set[tuple[str, float]] = {(LENGTH_FRACTION, round(f, 4)) for f in _fraction_matches(low)}
    for m in re.finditer(rf"{_NUM}\s*(?:%|percent)", low):
        pct = float(m.group(1))
        lead, tail = low[: m.start()].rstrip(), low[m.end() :].lstrip()
        removing = re.search(rf"{_SHRINK}\s+(?:it\s+)?(?:down\s+)?by$", lead) or re.match(
            r"(?:shorter|less|off)\b", tail
        )
        if not removing and not _has_length_context(low, m.start(), m.end()):
            continue
        found.add((LENGTH_FRACTION, round((100 - pct if removing else pct) / 100, 4)))
    for m in re.finditer(rf"{_NUM}[\s-]*(?:minutes?|mins?)\b", low):
        words = low[: m.start()].split()[-1:]
        if words and words[0] in _NOT_A_LENGTH:
            continue
        if not _has_length_context(low, m.start(), m.end()):
            continue
        found.add((LENGTH_SECONDS, round(float(m.group(1)) * 60, 1)))
    hour = re.search(r"\bhalf an hour\b", low)
    if hour and _has_length_context(low, hour.start(), hour.end()):
        found.add((LENGTH_SECONDS, 1800.0))
    if len(found) != 1:
        return None
    kind, value = next(iter(found))
    if kind == LENGTH_FRACTION and not 0 < value < 1:
        return None
    return (kind, value) if value > 0 else None


def length_target_s(length: tuple[str, float] | None, duration_s: float | None) -> int | None:
    """A length intent as seconds kept (a fraction needs the video's duration)."""
    if length is None:
        return None
    kind, value = length
    if kind == LENGTH_FRACTION:
        if not duration_s:
            return None
        value = value * duration_s
    target_s = int(round(value))
    return target_s if target_s >= MIN_TARGET_S else None


def effective_target_s(
    cfg,
    preset_id: str | None,
    duration_s: float | None,
    length: tuple[str, float] | None = None,
) -> int | None:
    """The target length (s): a built-in preset's, else the given length intent (a saved preset's
    explicit length, or the one read from the description); None when there is none or the video
    is already short enough to fit the band."""
    target_s = cfg.preset_target_s.get(preset_id or "")
    if target_s is None:
        target_s = length_target_s(length, duration_s)
    if target_s is None:
        return None
    if duration_s and duration_s <= target_band(target_s, cfg.length_tolerance)[1]:
        return None
    return target_s


def _padded_s(part: Part, cfg) -> float:
    return (part.end_ms - part.start_ms) / 1000.0 + cfg.pad_before_s + cfg.pad_after_s


def _trim_to(part: Part, units: list[Unit], budget_s: float, cfg) -> Part | None:
    """The leading units of `part` that fit `budget_s` (padding included), cut at a unit
    boundary; None when not even the first unit fits or the part has no unit ids."""
    if part.first is None or part.last is None:
        return None
    last = None
    for n in range(part.first, part.last + 1):
        if units[n - 1].end - units[part.first - 1].start + cfg.pad_before_s + cfg.pad_after_s > (
            budget_s
        ):
            break
        last = n
    if last is None:
        return None
    return Part(
        part.label,
        part.start_ms,
        int(units[last - 1].end * 1000),
        part.rank,
        part.first,
        last,
    )


def select_for_target(
    parts: list[Part], units: list[Unit], cfg, target_s: int
) -> tuple[list[Part], float]:
    """Pick parts by importance until the target is met; `(parts in video order, length in s)`.

    Parts are taken by rank (parts without one count in video order, after the ranked ones).
    A part that would push the total past the band is trimmed at a unit boundary to fit; the
    selection stops once the target is reached. A model answer shorter than the band returns
    everything it gave, so the caller can see the shortfall.
    """
    low, high = target_band(target_s, cfg.length_tolerance)
    pool_s = sum(_padded_s(p, cfg) for p in parts)
    if pool_s < low:
        return list(parts), pool_s
    order = sorted(
        range(len(parts)),
        key=lambda i: (parts[i].rank if parts[i].rank is not None else len(parts) + i + 1, i),
    )
    chosen: list[Part] = []
    total = 0.0
    for i in order:
        if total >= target_s:
            break
        part = parts[i]
        length = _padded_s(part, cfg)
        if total + length > high:
            trimmed = _trim_to(part, units, high - total, cfg)
            if trimmed is None:
                continue
            part, length = trimmed, _padded_s(trimmed, cfg)
        chosen.append(part)
        total += length
    chosen.sort(key=lambda p: p.start_ms)
    return chosen, total


@dataclass
class Chunk:
    """One excerpt of a long transcript: consecutive units, the first few shared with the
    previous excerpt (`core_first` is the first unit this excerpt owns)."""

    index: int
    units: list[Unit]
    core_first: int

    @property
    def core(self) -> list[Unit]:
        return [u for u in self.units if u.n >= self.core_first]


@dataclass
class Candidate:
    """A part an excerpt proposed, as the reduce call sees it: unit ids, label and its rank
    (`rank` of `of`) inside the excerpt that proposed it."""

    first: int
    last: int
    label: str
    rank: int
    of: int


def plan_chunks(
    units: list[Unit],
    chapters: list[tuple[float, str]],
    budget_chars: int,
    overlap_units: int,
) -> list[Chunk]:
    """Split `units` into excerpts of at most about `budget_chars` characters each.

    Chapter starts are preferred boundaries: a chapter is never cut unless it alone exceeds the
    budget (then it is split evenly at unit boundaries) and neighbouring chapters are packed
    together while they fit. Every excerpt but the first starts `overlap_units` units early.
    """
    costs = [len(unit_line(u)) + 1 for u in units]
    biggest = max(costs)
    room = max(budget_chars - overlap_units * biggest, biggest)
    starts = [u.start for u in units]
    cuts = {0}
    for at, _title in chapters:
        i = bisect.bisect_left(starts, at)
        if 0 < i < len(units):
            cuts.add(i)
    bounds = sorted(cuts) + [len(units)]
    pieces: list[tuple[int, int]] = []
    for a, b in zip(bounds, bounds[1:], strict=False):
        total = sum(costs[a:b])
        if total <= room:
            pieces.append((a, b))
            continue
        limit = min(room, total / math.ceil(total / room) + biggest)
        at, acc = a, 0
        for i in range(a, b):
            if acc + costs[i] > limit and i > at:
                pieces.append((at, i))
                at, acc = i, 0
            acc += costs[i]
        pieces.append((at, b))
    spans: list[tuple[int, int]] = []
    held = 0
    for a, b in pieces:
        cost = sum(costs[a:b])
        if spans and held + cost <= room:
            spans[-1] = (spans[-1][0], b)
            held += cost
        else:
            spans.append((a, b))
            held = cost
    return [
        Chunk(k, units[max(0, a - overlap_units) if k else 0 : b], units[a].n)
        for k, (a, b) in enumerate(spans)
    ]


def chapters_between(
    chapters: list[tuple[float, str]], start: float, end: float
) -> list[tuple[float, str]]:
    """The chapters an excerpt from `start` to `end` touches: the one running at its start
    and every later one that begins before `end`."""
    before = [c for c in chapters if c[0] <= start]
    inside = [c for c in chapters if start < c[0] < end]
    return before[-1:] + inside


def candidates_from(parts: list[Part]) -> list[Candidate]:
    """The parts one excerpt proposed as candidates: each carries its rank among them (parts
    without a rank count in video order, after the ranked ones)."""
    order = sorted(
        range(len(parts)),
        key=lambda i: (parts[i].rank if parts[i].rank is not None else len(parts) + i + 1, i),
    )
    position = {i: pos + 1 for pos, i in enumerate(order)}
    return [
        Candidate(p.first or 0, p.last or 0, p.label, position[i], len(parts))
        for i, p in enumerate(parts)
    ]


def merge_candidates(cands: list[Candidate]) -> list[Candidate]:
    """Candidates in video order; those of neighbouring excerpts that share units (the overlap)
    become one, with the label and rank of the better of the two."""
    out: list[Candidate] = []
    for cand in sorted(cands, key=lambda c: (c.first, c.last)):
        if out and cand.first <= out[-1].last:
            top = out[-1]
            best = cand if cand.rank / cand.of < top.rank / top.of else top
            out[-1] = Candidate(top.first, max(top.last, cand.last), best.label, best.rank, best.of)
        else:
            out.append(cand)
    return out


def candidate_units(cands: list[Candidate], units: list[Unit], excerpt_chars: int) -> list[Unit]:
    """The candidates as numbered lines for the reduce call: id (1..n), the real time range,
    label, rank in its excerpt and the start of its text."""
    out: list[Unit] = []
    for i, c in enumerate(cands, 1):
        text = " ".join(u.text for u in units[c.first - 1 : c.last])
        if len(text) > excerpt_chars:
            text = text[:excerpt_chars].rstrip() + "..."
        label = f"{c.label} (rank {c.rank} of {c.of} in its excerpt)"
        out.append(Unit(i, units[c.first - 1].start, units[c.last - 1].end, f"{label}: {text}"))
    return out


def expand_candidate_parts(
    parts: list[Part], cands: list[Candidate], units: list[Unit]
) -> list[Part]:
    """The reduce answer (parts over candidate ids) as parts over the real units: one part per
    candidate, so the gaps between candidates stay out of the cut."""
    out: list[Part] = []
    for part in parts:
        for k in range(part.first or 0, (part.last or 0) + 1):
            c = cands[k - 1]
            out.append(
                Part(
                    c.label,
                    int(units[c.first - 1].start * 1000),
                    int(units[c.last - 1].end * 1000),
                    part.rank,
                    c.first,
                    c.last,
                )
            )
    return out


def split_candidates(
    cands: list[Candidate], units: list[Unit], budget_chars: int, excerpt_chars: int
) -> list[list[Candidate]]:
    """Groups of consecutive candidates whose lines fit `budget_chars` (one group at least)."""
    shown = candidate_units(cands, units, excerpt_chars)
    groups: list[list[Candidate]] = [[]]
    held = 0
    for cand, line in zip(cands, shown, strict=True):
        cost = len(unit_line(line)) + 1
        if groups[-1] and held + cost > budget_chars:
            groups.append([])
            held = 0
        groups[-1].append(cand)
        held += cost
    return groups


def finalize_parts(
    parts: list[Part],
    cfg,
    *,
    guard: bool,
    duration_s: float | None,
    guard_max: bool | None = None,
) -> tuple[list[Part], float | None]:
    """Pad, merge and drop the kept parts; check how much of the video survives.

    Gaps under `cuts.merge_gap_s` are merged, parts under `cuts.min_part_s` are dropped, and
    boundaries are padded `pad_before_s`/`pad_after_s`. A cut keeping under `min_keep_frac`
    ("removes almost everything") is refused while `guard` is on. A cut over `max_keep_frac`
    ("nothing to cut") is refused only while `guard_max` is on (it defaults to `guard`); a
    named preset turns it off, because a removal preset that keeps nearly all is a valid answer.
    """
    merged: list[Part] = []
    duration_ms = int(duration_s * 1000) if duration_s else None
    for part in parts:
        start = max(0, part.start_ms - int(cfg.pad_before_s * 1000))
        end = part.end_ms + int(cfg.pad_after_s * 1000)
        if duration_ms is not None:
            end = min(end, duration_ms)  # the last part must not pad past the video end
        if merged and (start - merged[-1].end_ms) < cfg.merge_gap_s * 1000:
            merged[-1] = Part(merged[-1].label, merged[-1].start_ms, end)
        else:
            merged.append(Part(part.label, start, end))
    kept = [p for p in merged if p.end_ms - p.start_ms >= cfg.min_part_s * 1000]
    if not kept:
        raise CutRefused("Nothing was worth keeping, so there is no cut.")
    kept_ms = sum(p.end_ms - p.start_ms for p in kept)
    if guard and duration_s:
        duration_ms = int(duration_s * 1000)
        frac = kept_ms / duration_ms
        if frac < cfg.min_keep_frac:
            raise CutRefused(
                f"This cut would remove almost everything: it keeps only "
                f"{cut_clock(kept_ms)} of {cut_clock(duration_ms)} ({round(frac * 100)} %). "
                "Try a less aggressive cut, or another preset."
            )
        if (guard if guard_max is None else guard_max) and frac > cfg.max_keep_frac:
            raise CutRefused(
                f"Nothing to cut: this keeps {cut_clock(kept_ms)} of "
                f"{cut_clock(duration_ms)} ({round(frac * 100)} %). "
                "Try a more specific cut, or another preset."
            )
    return kept, round(kept_ms / 1000.0, 1)


def skip_ranges_ms(parts: list[Part], duration_ms: int) -> list[list[int]]:
    """The complement of the kept parts: what the TV jumps over, sorted and non-overlapping."""
    skips: list[list[int]] = []
    at = 0
    for part in parts:
        if part.start_ms > at:
            skips.append([at, min(part.start_ms, duration_ms)])
        at = max(at, part.end_ms)
    if at < duration_ms:
        skips.append([at, duration_ms])
    return [pair for pair in skips if pair[1] > pair[0]]


def cut_document(
    *,
    video_id: str,
    thash: str,
    model: str,
    parts: list[Part],
    summary: str,
    label: str,
    duration_s: float | None,
    source: SourceRef | dict[str, Any] | None,
    preset_id: str | None,
    built_at: float | None = None,
    target_s: int | None = None,
    transitions: list[dict[str, Any]] | None = None,
    mode: str = "quick",
) -> dict[str, Any]:
    """The wire document the phone and the TV read: kept parts, skip ranges in ms, the transcript
    hash and the length the cut was built for (the TV refuses a cut whose length differs)."""
    duration_ms = int((duration_s or 0) * 1000)
    if not duration_ms and parts:
        duration_ms = parts[-1].end_ms
    kept_ms = sum(p.end_ms - p.start_ms for p in parts)
    doc = {
        "version": CUT_DOC_VERSION,
        "video_id": video_id,
        "transcript_hash": thash,
        "duration_ms": duration_ms,
        "label": label[:80],
        "summary": (summary or "")[:300],
        "parts": [{"label": p.label, "start_ms": p.start_ms, "end_ms": p.end_ms} for p in parts],
        "skip_ranges_ms": skip_ranges_ms(parts, duration_ms),
        "kept_ms": kept_ms,
        "kept_s": round(kept_ms / 1000.0, 1),
        "target_s": target_s,
        "preset_id": preset_id,
        "model": model,
        "mode": mode,
        "built_at": built_at or time.time(),
    }
    if source is not None:
        doc["source"] = source.as_doc() if isinstance(source, SourceRef) else dict(source)
    if transitions is not None:
        doc["transitions"] = transitions
    return doc


class CutService:
    """The queue of cut requests and their builds: one async task per request, a per-user cap on
    concurrent builds, and one shared cut per (video, preset or prompt, model, transcript)."""

    def __init__(
        self,
        cfg: Config,
        db: Database,
        llm: LLMClient,
        transcripts: TranscriptService,
        prompts: PromptStore,
        jobs: JobQueue,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.transcripts, self.prompts, self.jobs = transcripts, prompts, jobs
        self.engine = CutEngine(cfg.cuts, lambda: cfg.llm.cuts, llm)
        self._tasks: dict[str, asyncio.Task] = {}
        # One build in flight per cache key: a second request with the same key waits on the
        # leader's future instead of calling the model again (shared builds, plan v2).
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}

    # ---- configuration --------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self.cfg.llm.cuts is not None

    def presets(self, user: str) -> list[Prompt]:
        return self.prompts.cut_prompts(user)

    # ---- rows -----------------------------------------------------------------------------------

    def _row(self, request_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM cut_requests WHERE id=?", [request_id])
        return dict(row) if row else None

    def _set_state(
        self,
        request_id: str,
        state: str,
        *,
        error: str | None = None,
        cut_key: str | None = None,
        finished: bool = False,
    ) -> None:
        self.db.execute(
            "UPDATE cut_requests SET state=?, error=?, cut_key=COALESCE(?, cut_key),"
            " updated_at=?, finished_at=COALESCE(?, finished_at) WHERE id=?",
            [state, error, cut_key, time.time(), time.time() if finished else None, request_id],
        )

    def _meta(self, video_id: str) -> dict[str, Any]:
        return self.transcripts.cached_meta(video_id) or {}

    def building_count(self, user: str) -> int:
        marks = ",".join("?" * len(BUILDING_STATES))
        row = self.db.one(
            f"SELECT COUNT(*) AS n FROM cut_requests WHERE user=? AND state IN ({marks})",
            [user, *BUILDING_STATES],
        )
        return int(row["n"])

    def _check_cap(self, user: str) -> None:
        if self.building_count(user) >= self.cfg.cuts.max_active_per_user:
            raise CutRefused(
                "Too many cuts are already being built; try again when one has finished.",
                status=429,
            )

    def _validate_prompt(self, prompt: str | None) -> str | None:
        if prompt is None:
            return None
        prompt = prompt.strip()
        if not prompt:
            raise CutRefused("The description of the cut is empty.")
        if len(prompt) > self.cfg.cuts.max_prompt_chars:
            raise CutRefused(
                f"The description is longer than {self.cfg.cuts.max_prompt_chars} characters."
            )
        return prompt

    def _refuse_watched(self) -> None:
        if not watched_available(self.cfg):
            raise CutRefused(WATCHED_REASON)

    def _clean_channel_id(self, channel_id: str | None) -> str | None:
        if channel_id is None:
            return None
        channel_id = channel_id.strip()
        if not channel_id:
            return None
        if len(channel_id) > MAX_CHANNEL_ID_CHARS:
            raise CutRefused(
                f"A channel id is at most {MAX_CHANNEL_ID_CHARS} characters.", status=400
            )
        return channel_id

    def _clean_channel_name(self, channel_name: str | None) -> str | None:
        if channel_name is None:
            return None
        channel_name = " ".join(channel_name.split())
        return channel_name[:MAX_CHANNEL_NAME_CHARS] or None

    def _channel_context(
        self,
        user: str,
        video_id: str,
        channel_id: str | None = None,
        channel_name: str | None = None,
    ) -> tuple[str | None, str | None, str | None]:
        """The video's channel and the owner's mode for it, from the request or the cached meta."""
        meta = self._meta(video_id)
        channel_id = self._clean_channel_id(channel_id) or self._clean_channel_id(
            meta.get("channel_id")
        )
        channel_name = self._clean_channel_name(channel_name) or self._clean_channel_name(
            meta.get("channel")
        )
        if not channel_id:
            return None, channel_name, None
        row = self.db.one(
            "SELECT channel_name, mode FROM cut_channel_modes WHERE user=? AND channel_id=?",
            [user, channel_id],
        )
        if row is None:
            return channel_id, channel_name, None
        return channel_id, row["channel_name"] or channel_name, row["mode"]

    def _resolve_mode(
        self,
        requested: str | None,
        user_mode: str | None,
        channel_mode: str | None = None,
    ) -> tuple[str, str]:
        """The mode a request runs in and the rule that decided it.

        An explicit unavailable mode is refused; a watched default from the channel, the owner or
        the server falls back to quick but still reports the rule that made the choice.
        """
        if requested is not None:
            if requested == "watched":
                self._refuse_watched()
            return requested, MODE_RULE_REQUEST
        for mode, rule in (
            (channel_mode, MODE_RULE_CHANNEL),
            (user_mode, MODE_RULE_USER),
            (self.cfg.cuts.default_mode, MODE_RULE_SERVER),
        ):
            if not mode:
                continue
            if mode == "watched" and not watched_available(self.cfg):
                return "quick", rule
            return mode, rule
        return "quick", MODE_RULE_SERVER

    # ---- channel defaults -----------------------------------------------------------------------

    def channel_modes(self, user: str) -> list[dict[str, Any]]:
        """Every channel the owner has cut or given a default, by name then id.

        A channel with no stored default has `mode: null`; the phone lists it so the owner can
        set one there without waiting for the TV.
        """
        rows = self.db.all(
            "SELECT channel_id, channel_name, mode, updated_at FROM cut_channel_modes WHERE user=?",
            [user],
        )
        channels = {row["channel_id"]: dict(row) for row in rows}
        seen = self.db.all(
            "SELECT DISTINCT video_id, channel_id FROM cut_requests WHERE user=?",
            [user],
        )
        for row in seen:
            meta = self._meta(row["video_id"])
            channel_id = row["channel_id"] or meta.get("channel_id")
            if not isinstance(channel_id, str):
                continue
            channel_id = channel_id.strip()[:MAX_CHANNEL_ID_CHARS]
            if not channel_id:
                continue
            channel_name = self._clean_channel_name(meta.get("channel"))
            if channel_id not in channels:
                channels[channel_id] = {
                    "channel_id": channel_id,
                    "channel_name": channel_name,
                    "mode": None,
                    "updated_at": None,
                }
            elif not channels[channel_id]["channel_name"]:
                channels[channel_id]["channel_name"] = channel_name
        return sorted(
            channels.values(),
            key=lambda row: ((row["channel_name"] or "").lower(), row["channel_id"]),
        )

    def channel_mode(self, user: str, channel_id: str) -> dict[str, Any] | None:
        row = self.db.one(
            "SELECT channel_id, channel_name, mode, updated_at FROM cut_channel_modes"
            " WHERE user=? AND channel_id=?",
            [user, self._clean_channel_id(channel_id)],
        )
        return dict(row) if row else None

    def set_channel_mode(
        self,
        user: str,
        channel_id: str,
        mode: str,
        channel_name: str | None = None,
    ) -> dict[str, Any]:
        """Store the owner's default mode for a channel; `watched` must be configured."""
        channel_id = self._clean_channel_id(channel_id)
        if not channel_id:
            raise CutRefused("A channel id is required.", status=400)
        if mode not in MODE_LABELS:
            raise CutRefused(f"Unknown cut mode {mode}.", status=400)
        if mode == "watched":
            self._refuse_watched()
        channel_name = self._clean_channel_name(channel_name)
        existing = self.channel_mode(user, channel_id)
        if channel_name is None and existing is not None:
            channel_name = existing["channel_name"]
        now = time.time()
        self.db.execute(
            "INSERT INTO cut_channel_modes(user,channel_id,channel_name,mode,updated_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(user,channel_id) DO UPDATE SET"
            " channel_name=excluded.channel_name, mode=excluded.mode, updated_at=excluded.updated_at",
            [user, channel_id, channel_name, mode, now],
        )
        return {
            "channel_id": channel_id,
            "channel_name": channel_name,
            "mode": mode,
            "updated_at": now,
        }

    def clear_channel_mode(self, user: str, channel_id: str) -> bool:
        """Forget the owner's default for a channel, so the next rule decides again."""
        channel_id = self._clean_channel_id(channel_id)
        if not channel_id:
            raise CutRefused("A channel id is required.", status=400)
        return (
            self.db.execute_rc(
                "DELETE FROM cut_channel_modes WHERE user=? AND channel_id=?",
                [user, channel_id],
            )
            > 0
        )

    # ---- the queue ------------------------------------------------------------------------------

    def create(
        self,
        user: str,
        video_id: str,
        *,
        source: str = "",
        preset: str | None = None,
        prompt: str | None = None,
        await_prompt: bool = False,
        mode: str | None = None,
        user_mode: str | None = None,
        channel_id: str | None = None,
        source_kind: str = "youtube",
        source_key: str | None = None,
        release_key: str | None = None,
        release_duration_ms: int | None = None,
    ) -> dict[str, Any]:
        """Queue a cut. Exactly one of `preset` / `prompt`; `await_prompt` creates an empty
        request the phone fills later. An identical active request is returned as-is."""
        if not self.configured:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        channel_id, _channel_name, channel_mode = self._channel_context(user, video_id, channel_id)
        mode, mode_rule = self._resolve_mode(mode, user_mode, channel_mode)
        server_mode = self.cfg.cuts.default_mode
        source_key = source_key or f"{source_kind}:{video_id}"
        prompt = self._validate_prompt(prompt)
        if prompt is not None and preset is not None:
            raise CutRefused("A cut takes a preset or a description, not both.", status=400)
        if prompt is None and not await_prompt:
            if preset is None:
                raise CutRefused("A cut needs a preset or a description.")
            if not any(p.id == preset for p in self.presets(user)):
                raise CutRefused(f"Unknown cut preset {preset}.")
        if await_prompt and preset is not None:
            raise CutRefused("A request that waits for a description cannot name a preset.")
        existing = self._active_same(
            user,
            video_id,
            preset,
            prompt,
            await_prompt,
            mode=mode,
            source_key=source_key,
            release_key=release_key,
        )
        if existing is not None:
            return existing
        if not await_prompt:
            self._check_cap(user)
        request_id = uuid.uuid4().hex[:12]
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        title = self._meta(video_id).get("title")
        self.db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
            "updated_at,kind,title,priority) VALUES(?,?,?,'',NULL,'queued',0,?,?, 'cuts',?,?)",
            [job_id, user, video_id, now, now, title, INTERACTIVE],
        )
        self.db.execute(
            "INSERT INTO cut_requests(id,user,video_id,source,preset_id,prompt,state,job_id,"
            "created_at,updated_at,source_kind,source_key,release_key,release_duration_ms,mode,"
            "mode_rule,channel_id,channel_mode,user_mode,server_mode)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                request_id,
                user,
                video_id,
                source,
                preset,
                prompt,
                "waiting" if await_prompt else "building",
                job_id,
                now,
                now,
                source_kind,
                source_key,
                release_key,
                release_duration_ms,
                mode,
                mode_rule,
                channel_id,
                channel_mode,
                user_mode,
                server_mode,
            ],
        )
        origin = events.current_origin()
        self.jobs.events.record(
            job_id,
            events.QUEUED,
            events.OK,
            {
                "kind": "cuts",
                "user": user,
                "client": source or (origin.client if origin else "server"),
                "endpoint": origin.endpoint if origin else None,
                "video_id": video_id,
                "title": self._meta(video_id).get("title"),
                "preset": preset,
                "prompt": prompt,
                "await_prompt": await_prompt,
            },
            ts=now,
        )
        if not await_prompt:
            self._start(request_id)
        return self._row(request_id)  # type: ignore[return-value]

    def _active_same(
        self,
        user: str,
        video_id: str,
        preset: str | None,
        prompt: str | None,
        await_prompt: bool,
        *,
        mode: str,
        source_key: str,
        release_key: str | None,
    ) -> dict[str, Any] | None:
        states = (*BUILDING_STATES, "waiting")
        marks = ",".join("?" * len(states))
        same = (
            f" AND COALESCE(source_key,'youtube:'||video_id)=? AND COALESCE(release_key,'')=?"
            f" AND mode=? AND state IN ({marks}) ORDER BY created_at DESC LIMIT 1"
        )
        tail = [source_key, release_key or "", mode, *states]
        if await_prompt:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id IS NULL"
                f" AND prompt IS NULL{same}",
                [user, video_id, *tail],
            )
        elif prompt is not None:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND prompt=?{same}",
                [user, video_id, prompt, *tail],
            )
        else:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id=?{same}",
                [user, video_id, preset, *tail],
            )
        return dict(row) if row else None

    def fill(
        self,
        request_id: str,
        user: str,
        prompt: str,
        mode: str | None = None,
        user_mode: str | None = None,
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        """A waiting request gets its description from the phone; the build starts."""
        if not self.configured:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        row = self._row(request_id)
        if row is None or row["user"] != user:
            raise CutRefused("No such cut request.", status=404)
        if row["state"] != "waiting":
            raise CutRefused("This cut request is not waiting for a description any more.")
        prompt = self._validate_prompt(prompt)
        if prompt is None:
            raise CutRefused("The description of the cut is empty.")
        channel_id, _channel_name, channel_mode = self._channel_context(
            user, row["video_id"], channel_id or row["channel_id"]
        )
        server_mode = self.cfg.cuts.default_mode
        if mode is not None:
            chosen_mode, mode_rule = self._resolve_mode(mode, user_mode, channel_mode)
        else:
            chosen_mode, mode_rule = row["mode"], row["mode_rule"] or MODE_RULE_REQUEST
            channel_mode, user_mode, server_mode = (
                row["channel_mode"],
                row["user_mode"],
                row["server_mode"],
            )
        self._check_cap(user)
        self.db.execute(
            "UPDATE cut_requests SET prompt=?, mode=?, mode_rule=?, channel_id=?,"
            " channel_mode=?, user_mode=?, server_mode=?, state='building', updated_at=?"
            " WHERE id=?",
            [
                prompt,
                chosen_mode,
                mode_rule,
                channel_id,
                channel_mode,
                user_mode,
                server_mode,
                time.time(),
                request_id,
            ],
        )
        self.jobs.events.record(
            row["job_id"],
            events.PROMOTED,
            events.OK,
            {
                "filled_by": user,
                "message": "The description arrived from the phone; the cut is being built.",
            },
        )
        self._start(request_id)
        return self._row(request_id)  # type: ignore[return-value]

    def dismiss(self, request_id: str, user: str) -> None:
        row = self._row(request_id)
        if row is None or row["user"] != user:
            raise CutRefused("No such cut request.", status=404)
        task = self._tasks.pop(request_id, None)
        if task is not None:
            task.cancel()
        self._set_state(request_id, "dismissed", finished=True)
        if row["job_id"]:
            now = time.time()
            self.db.execute(
                "UPDATE jobs SET status='cancelled', error='Dismissed', updated_at=?,"
                " finished_at=? WHERE id=? AND status IN ('queued','running')",
                [now, now, row["job_id"]],
            )
            self.jobs.events.record(
                row["job_id"],
                events.FINISHED,
                events.CANCELLED,
                {"by": user, "message": "The cut request was dismissed."},
            )

    def queue(self, user: str) -> list[dict[str, Any]]:
        """The owner's cut requests, newest first, with the video facts for the cards."""
        rows = self.db.all(
            "SELECT * FROM cut_requests WHERE user=? AND state!='dismissed'"
            f" ORDER BY created_at DESC LIMIT {QUEUE_LIMIT}",
            [user],
        )
        return [self.card(dict(row)) for row in rows]

    def card(self, row: dict[str, Any]) -> dict[str, Any]:
        out = {
            "id": row["id"],
            "video_id": row["video_id"],
            "state": row["state"],
            "source": row["source"],
            "mode": row["mode"],
            "mode_rule": row["mode_rule"] or MODE_RULE_REQUEST,
            "preset_id": row["preset_id"],
            "prompt": row["prompt"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **{
                k: v
                for k, v in self._meta(row["video_id"]).items()
                if k in ("title", "channel", "duration_s")
            },
        }
        if row["channel_id"]:
            out["channel_id"] = row["channel_id"]
        if row["state"] in BUILDING_STATES and row["job_id"]:
            out["stage"] = self._last_stage(row["job_id"])
            progress = self._last_progress(row["job_id"])
            if progress:
                out["progress"] = progress
        if row["state"] == "ready" and row["cut_key"]:
            cut = self.db.one("SELECT json FROM cuts WHERE cache_key=?", [row["cut_key"]])
            if cut:
                out["cut"] = json.loads(cut["json"])
        return out

    def _last_stage(self, job_id: str) -> str | None:
        row = self.db.one(
            "SELECT stage FROM job_events WHERE job_id=? AND stage NOT IN ('delivered','queued')"
            " ORDER BY id DESC LIMIT 1",
            [job_id],
        )
        return row["stage"] if row else None

    def _last_progress(self, job_id: str) -> dict[str, int] | None:
        """`{"done","of"}` of the excerpts a long video has been through, while the map runs."""
        row = self.db.one(
            "SELECT stage, detail FROM job_events WHERE job_id=? AND stage NOT IN"
            " ('delivered','queued') ORDER BY id DESC LIMIT 1",
            [job_id],
        )
        if row is None or row["stage"] != STAGE_MAP or not row["detail"]:
            return None
        detail = json.loads(row["detail"])
        if "done" not in detail or "of" not in detail:
            return None
        return {"done": int(detail["done"]), "of": int(detail["of"])}

    def get(self, request_id: str, user: str) -> dict[str, Any] | None:
        """One request for its owner, with the cut and the build report once it has them."""
        row = self._row(request_id)
        if row is None or row["user"] != user:
            return None
        out = self.card(row)
        if row["job_id"]:
            out["job_id"] = row["job_id"]
        if row["prompt"]:
            out["instruction"] = row["prompt"]
        if row["raw_answer"]:
            out["raw_answer"] = row["raw_answer"][: self.cfg.cuts.max_report_chars]
        return out

    async def get_wait(self, request_id: str, user: str, wait_ms: int | None) -> dict[str, Any]:
        """`GET /v1/cuts/{id}`: poll a waiting or building request until its state changes or
        `wait_ms` (capped) has passed."""
        doc = self.get(request_id, user)
        if doc is None:
            raise CutRefused("No such cut request.", status=404)
        wait_s = max(
            0.0,
            min(
                wait_ms if wait_ms is not None else self.cfg.cuts.default_wait_ms,
                self.cfg.cuts.wait_ms_cap,
            ),
        )
        deadline = time.monotonic() + wait_s / 1000.0
        while doc["state"] in (*BUILDING_STATES, "waiting") and time.monotonic() < deadline:
            await asyncio.sleep(min(self.cfg.cuts.poll_s, max(0.05, deadline - time.monotonic())))
            doc = self.get(request_id, user) or doc
        return doc

    # ---- the picker -----------------------------------------------------------------------------

    def presets_state(
        self,
        user: str,
        video_id: str,
        user_mode: str | None = None,
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        """Every preset with its state for this video: what the TV's picker and the phone show.

        The default follows request > channel > owner > server; `mode_rule` says which one chose.
        `channel_mode` is the owner's stored override for the video's channel, or null.
        """
        available = watched_available(self.cfg)
        channel_id, channel_name, channel_mode = self._channel_context(user, video_id, channel_id)
        default_mode, mode_rule = self._resolve_mode(None, user_mode, channel_mode)
        out = []
        for prompt in self.presets(user):
            by_mode = {
                mode: self._preset_state(user, video_id, prompt, mode) for mode in MODE_LABELS
            }
            out.append(
                {
                    "id": prompt.id,
                    "label": prompt.label,
                    **by_mode[default_mode],
                    "by_mode": by_mode,
                }
            )
        modes = [
            {
                "id": mode,
                "label": label,
                "default": mode == default_mode,
                "available": available if mode == "watched" else True,
                **({} if mode != "watched" or available else {"reason": WATCHED_REASON}),
            }
            for mode, label in MODE_LABELS.items()
        ]
        return {
            "configured": self.configured,
            "default_mode": default_mode,
            "mode_rule": mode_rule,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_mode": channel_mode,
            "modes": modes,
            "presets": out,
        }

    def _preset_state(self, user: str, video_id: str, prompt: Prompt, mode: str) -> dict[str, Any]:
        if mode == "watched" and not watched_available(self.cfg):
            return {"state": "unavailable", "reason": WATCHED_REASON}
        row = self.db.one(
            "SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id=?"
            " AND mode=? AND state IN ('waiting','building','needs_transcript')"
            " ORDER BY created_at DESC LIMIT 1",
            [user, video_id, prompt.id, mode],
        )
        if row:
            return {"state": row["state"], "request_id": row["id"]}
        cut = self._ready_cut(video_id, prompt, mode)
        if cut is not None:
            return {"state": "ready", "cut": cut}
        failed = self.db.one(
            "SELECT id, error FROM cut_requests WHERE user=? AND video_id=?"
            " AND preset_id=? AND mode=? AND state='failed' ORDER BY created_at DESC LIMIT 1",
            [user, video_id, prompt.id, mode],
        )
        if failed:
            return {"state": "failed", "request_id": failed["id"], "error": failed["error"]}
        return {"state": "none"}

    def _ready_cut(
        self, video_id: str, prompt: Prompt, mode: str = "quick"
    ) -> dict[str, Any] | None:
        """The stored cut for this preset, unless the transcript or the `[llm.cuts]` model
        changed since it was built."""
        model = self.cfg.llm.cuts.model if self.cfg.llm.cuts else ""
        duration = self._meta(video_id).get("duration_s")
        target_s = self.target_for(
            prompt.id, float(duration) if duration else None, prompt.template, prompt
        )
        row = self.db.one(
            "SELECT json, transcript_hash FROM cuts WHERE video_id=? AND version=? AND model=?"
            " AND COALESCE(source_key,'youtube:'||video_id)=?"
            " AND COALESCE(release_key,'')='' AND mode=?"
            " ORDER BY created_at DESC LIMIT 1",
            [
                video_id,
                self._version(prompt.id, prompt.template, target_s),
                model,
                f"youtube:{video_id}",
                mode,
            ],
        )
        if row is None:
            return None
        transcript = self.transcripts.cached(video_id)
        if transcript is not None and transcript.segments:
            if transcript_hash(transcript.segments) != row["transcript_hash"]:
                return None
        return json.loads(row["json"])

    # ---- the build ------------------------------------------------------------------------------

    def start(self) -> None:
        """Resume the builds a restart interrupted (idempotent: the cache absorbs the repeats)."""
        rows = self.db.all(
            "SELECT id FROM cut_requests WHERE state IN ('building','needs_transcript')"
        )
        for row in rows:
            self._start(row["id"])

    async def stop(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    def _start(self, request_id: str) -> None:
        if request_id in self._tasks:
            return
        task = asyncio.create_task(self._build(request_id))
        self._tasks[request_id] = task
        task.add_done_callback(lambda _t: self._tasks.pop(request_id, None))
        task.add_done_callback(lambda t: t.cancelled() or t.exception())

    async def _build(self, request_id: str) -> None:
        row = self._row(request_id)
        if row is None or row["state"] not in ("building", "needs_transcript"):
            return
        self.db.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
            [time.time(), row["job_id"]],
        )
        trace = events.JobTrace(row["job_id"], self.jobs.events)
        token = events.bind(trace)
        try:
            trace.emit(events.STARTED, events.OK, kind="cuts", video_id=row["video_id"])
            await self._run_build(row, trace)
        except asyncio.CancelledError:
            raise
        except CutRefused as exc:
            self._fail(request_id, row["job_id"], exc.message)
        except LLMError:
            log.warning("cut %s: the model service failed", request_id, exc_info=True)
            self._fail(request_id, row["job_id"], "The model service is busy; try again.")
        except Exception:
            log.warning("cut %s failed", request_id, exc_info=True)
            self._fail(request_id, row["job_id"], "The cut could not be built; try again.")
        finally:
            events.unbind(token)

    def _fail(self, request_id: str, job_id: str, message: str) -> None:
        row = self._row(request_id)
        if row is None or row["state"] == "dismissed":
            return
        self._set_state(request_id, "failed", error=message, finished=True)
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET status='failed', error=?, updated_at=?, finished_at=? WHERE id=?",
            [message, now, now, job_id],
        )
        self.jobs.events.record(job_id, events.FAILED_STAGE, events.FAILED, {"message": message})

    def _dismissed(self, request_id: str) -> bool:
        row = self.db.one("SELECT state FROM cut_requests WHERE id=?", [request_id])
        return row is None or row["state"] == "dismissed"

    async def _run_build(self, row: dict[str, Any], trace: events.JobTrace) -> None:
        request_id, video_id = row["id"], row["video_id"]
        instruction, preset_id, _source = self._instruction(row)
        ref = source_ref(row)
        mode = row["mode"] or "quick"
        with events.stage(STAGE_TRANSCRIPT, video_id=video_id):
            transcript = await self._ensure_transcript(request_id, row)
            units = build_units(transcript.segments or [], self.cfg.cuts)
            if not units:
                raise CutRefused("This transcript has no timed speech to cut.")
            thash = transcript_hash(transcript.segments)
            meta = {**transcript.meta, **self._meta(video_id)}
            if not meta.get("duration_s"):
                await self.transcripts.ensure_length(video_id, wait_s=15.0)
                meta = {**meta, **self._meta(video_id)}
            chapters = parse_chapters(meta.get("description"))
            trace.emit(
                STAGE_TRANSCRIPT,
                events.OK,
                source=transcript.source,
                lang=transcript.lang,
                units=len(units),
                chars=len(transcript.text),
            )
        if self._dismissed(request_id):
            return
        duration_s = meta.get("duration_s")
        duration_s = float(duration_s) if duration_s else None
        saved = next((p for p in self.presets(row["user"]) if p.id == preset_id), None)
        target_s = self.target_for(preset_id, duration_s, instruction, saved)
        version = self._version(preset_id, instruction, target_s)
        model = self.cfg.llm.cuts.model if self.cfg.llm.cuts else ""
        cache_key = self._cache_key(video_id, version, model, thash, source=ref, mode=mode)
        hit = self.db.one("SELECT json FROM cuts WHERE cache_key=?", [cache_key])
        if hit is not None:
            events.emit(STAGE_MODEL, events.SKIPPED, reason="cached")
            self._finish(request_id, row, cache_key, json.loads(hit["json"]))
            return
        while True:
            leader = self._inflight.get(cache_key)
            if leader is None:
                break
            events.emit(STAGE_MODEL, events.SKIPPED, reason="shared build")
            try:
                doc = await asyncio.shield(leader)
            except asyncio.CancelledError:
                # A cancellation of this request itself (the service stopping, the task being
                # cancelled) must not be swallowed into another build: without this check a
                # waiter would catch its own CancelledError, take the leader-dismissed branch
                # below and start a real model call while the server is shutting down.
                if (
                    asyncio.current_task().cancelling()
                    or self._dismissed(request_id)
                    or not leader.cancelled()
                ):
                    raise
                continue  # the leader was dismissed; its cache key is free again
            self._finish(request_id, row, cache_key, doc)
            return
        leader = asyncio.get_running_loop().create_future()
        leader.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        self._inflight[cache_key] = leader
        try:
            data, parts = await self.engine.pick_parts(units, chapters, meta, instruction, target_s)
            with events.stage(STAGE_CHECKING):
                guard = target_s is None and not (preset_id or "").endswith("highlights-5")
                # A named preset is a deliberate removal instruction, so keeping nearly all of the
                # video is a result, not "nothing to cut"; a typed prompt without a target keeps
                # the upper guard.
                guard_max = guard and preset_id is None
                parts, _kept_s = finalize_parts(
                    parts,
                    self.cfg.cuts,
                    guard=guard,
                    duration_s=duration_s,
                    guard_max=guard_max,
                )
                summary = removal_summary(
                    preset_id, parts, duration_s, str(data.get("summary") or "")
                )
                doc = cut_document(
                    video_id=video_id,
                    thash=thash,
                    model=model,
                    parts=parts,
                    summary=summary,
                    label=self._label(preset_id, row),
                    duration_s=duration_s,
                    source=ref,
                    preset_id=preset_id,
                    target_s=target_s,
                    mode=mode,
                )
                events.emit(
                    STAGE_CHECKING,
                    events.OK,
                    parts=len(parts),
                    kept_s=doc["kept_ms"] / 1000.0,
                    duration_s=duration_s,
                    target_s=target_s,
                )
            self.db.execute(
                "INSERT OR REPLACE INTO cuts(cache_key,video_id,version,preset_id,prompt,model,"
                "transcript_hash,json,duration_s,kept_s,created_at,source_kind,source_key,"
                "release_key,release_duration_ms,mode)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    cache_key,
                    video_id,
                    version,
                    preset_id,
                    row["prompt"],
                    model,
                    thash,
                    json.dumps(doc, ensure_ascii=False),
                    duration_s,
                    doc["kept_ms"] / 1000.0,
                    time.time(),
                    ref.kind,
                    ref.key,
                    ref.release_key,
                    ref.release_duration_ms,
                    mode,
                ],
            )
            self.db.execute(
                "UPDATE cut_requests SET raw_answer=?, updated_at=? WHERE id=?",
                [
                    json.dumps(data, ensure_ascii=False)[: self.cfg.cuts.max_report_chars],
                    time.time(),
                    request_id,
                ],
            )
            leader.set_result(doc)
        except Exception as exc:
            # A cancellation (the leader was dismissed) must NOT land on the future as an
            # exception: `set_exception(CancelledError())` finishes it without cancelling it,
            # and a waiting request would then re-raise and stay `building` forever. A
            # CancelledError reaches `finally` instead, which cancels the future and frees
            # the waiters to build the cut themselves.
            if not leader.done():
                leader.set_exception(exc)  # a waiter fails with the same reason
            raise
        finally:
            self._inflight.pop(cache_key, None)
            if not leader.done():
                leader.cancel()  # dismissed or gone without an answer: waiters build it themselves
        # A dismissed request stops here (dismiss already marked it and its job), but the
        # answer above was still checked, cached and handed to the waiters, so they do not
        # have to call the model again.
        if not self._dismissed(request_id):
            self._finish(request_id, row, cache_key, doc)

    def _finish(
        self, request_id: str, row: dict[str, Any], cache_key: str, doc: dict[str, Any]
    ) -> None:
        self._set_state(request_id, "ready", cut_key=cache_key, finished=True)
        now = time.time()
        self.db.execute(
            "UPDATE jobs SET status='ready', progress=1, updated_at=?, finished_at=? WHERE id=?",
            [now, now, row["job_id"]],
        )
        self.jobs.events.record(
            row["job_id"],
            events.FINISHED,
            events.OK,
            {
                "kept_s": doc["kept_ms"] / 1000.0,
                "parts": len(doc["parts"]),
                "label": doc["label"],
            },
        )

    def _instruction(self, row: dict[str, Any]) -> tuple[str, str | None, str]:
        """(task text, preset id or None, source) of a request."""
        if row["prompt"]:
            return row["prompt"], None, "prompt"
        preset_id = row["preset_id"] or ""
        prompt = next((p for p in self.presets(row["user"]) if p.id == preset_id), None)
        if prompt is None:
            raise CutRefused(f"Unknown cut preset {preset_id}.")
        return prompt.template, preset_id, "preset"

    def target_for(
        self,
        preset_id: str | None,
        duration_s: float | None,
        instruction: str,
        saved: Prompt | None = None,
    ) -> int | None:
        """Built-in target, else the saved preset's explicit length, else the length the
        description asks for (the built-ins' own wording is never read)."""
        length = None
        if saved is not None and (saved.length_min or saved.length_frac):  # one of them, see Prompt
            if saved.length_min:
                length = (LENGTH_SECONDS, saved.length_min * 60)
            else:
                length = (LENGTH_FRACTION, saved.length_frac)
        elif preset_id not in BUILTIN_CUT_IDS:
            length = parse_length_intent(instruction)
        return effective_target_s(self.cfg.cuts, preset_id, duration_s, length)

    def _label(self, preset_id: str | None, row: dict[str, Any]) -> str:
        if row["prompt"]:
            return row["prompt"]
        saved = next((p for p in self.presets(row["user"]) if p.id == preset_id), None)
        if saved is not None:
            return saved.label
        return PRESET_LABELS.get(preset_id or "", preset_id or "Cut")

    @staticmethod
    def _version(preset_id: str | None, instruction: str, target_s: int | None = None) -> str:
        mark = "cut" if preset_id else "prompt"
        text = instruction if target_s is None else f"{instruction}|target={target_s}"
        return f"{mark}:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    @staticmethod
    def _cache_key(
        video_id: str,
        version: str,
        model: str,
        thash: str,
        *,
        source: SourceRef | None = None,
        mode: str = "quick",
    ) -> str:
        part = video_id
        if source is not None:
            key = source.key or f"youtube:{video_id}"
            if key != f"youtube:{video_id}" or source.release_key:
                part = f"{key}|{source.release_key or ''}"
        if mode != "quick":
            part = f"{part}|{mode}"
        return hashlib.sha256(f"{part}|{version}|{model}|{thash}".encode()).hexdigest()

    async def _ensure_transcript(self, request_id: str, row: dict[str, Any]) -> Transcript:
        """A timed transcript for the cut: the cached one, else a queued refresh we wait for.

        A captions row without timings (an older fetch) is dropped so the queued transcript job
        really refetches them; an ASR row without timings is refused (speech recognition is not
        free to repeat). The dropped row is shared with summaries: if the refresh then fails,
        summaries lose that cached text too and must refetch it themselves — accepted, because
        a transcript without timings is useless for cuts."""
        video_id = row["video_id"]
        cached = self.transcripts.cached(video_id)
        if cached is not None and cached.segments:
            return cached
        if self._meta(video_id).get("is_live"):
            raise CutRefused("This is a live stream; live videos cannot be cut.")
        if cached is not None:
            if cached.source == SOURCE_ASR:
                raise CutRefused(
                    "The stored transcript has no timings, so a cut cannot be placed on it. "
                    "Rebuild the transcript first (a captions or transcribe job)."
                )
            self.db.execute("DELETE FROM transcripts WHERE video_id=?", [video_id])
        self._set_state(request_id, "needs_transcript")
        self.jobs.events.record(
            row["job_id"],
            STAGE_TRANSCRIPT,
            events.WARN,
            {"message": "No timed transcript yet; queued a refresh and waiting for it."},
        )
        job = self.jobs.enqueue_transcript(
            row["user"], video_id, self._meta(video_id).get("title"), priority=INTERACTIVE
        )
        deadline = time.monotonic() + self.cfg.cuts.transcript_wait_s
        while time.monotonic() < deadline:
            if self._dismissed(request_id):
                raise CutRefused("The cut request was dismissed.")
            await asyncio.sleep(self.cfg.cuts.poll_s)
            cached = self.transcripts.cached(video_id)
            if cached is not None and cached.segments:
                self._set_state(request_id, "building")
                return cached
            job_row = self.jobs.get(job["id"])
            if job_row and job_row["status"] in ("failed", "cancelled"):
                raise CutRefused(
                    "No transcript could be built for this video ("
                    + (job_row.get("error") or "transcription failed")
                    + ")."
                )
            if (
                job_row
                and job_row["status"] == "ready"
                and not (cached is not None and cached.segments)
            ):
                raise CutRefused(
                    "The transcript still has no timings after the refresh, so a cut cannot be "
                    "placed on it."
                )
        raise CutRefused(
            f"No transcript after {int(self.cfg.cuts.transcript_wait_s / 60)} min; try again later."
        )


class CutEngine:
    """Asks the cut model: one pass when the transcript fits `max_input_tokens`, otherwise map
    over excerpts and reduce over their candidates. Knows nothing of requests, jobs or the
    database, so the offline bench drives the same code."""

    def __init__(
        self,
        cfg: CutsConfig,
        task: Callable[[], LLMTask | None],
        llm: Any,
    ):
        self.cfg, self.task, self.llm = cfg, task, llm

    async def pick_parts(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
    ) -> tuple[Any, list[Part]]:
        """The model's final answer and the parts to keep (before padding and the checks)."""
        if self.fits(units, chapters, meta, instruction, target_s):
            task = self.task()
            with events.stage(
                STAGE_MODEL, model=task.model if task else "", units=len(units)
            ) as model_stage:
                data, parts = await self._ask_parts(units, chapters, meta, instruction, target_s)
                model_stage.set(answer=json.dumps(data, ensure_ascii=False))
            return data, parts
        return await self._map_reduce(units, chapters, meta, instruction, target_s)

    async def _ask_parts(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        *,
        candidates: list[Candidate] | None = None,
    ) -> tuple[Any, list[Part]]:
        """The model's answer as parts: one repair round for a broken answer and, with a target
        length, one retry that names the measured length when the answer is below the band.

        With `candidates` this is the reduce call: the model sees the candidates instead of the
        units and its answer is expanded back to parts over the real units."""
        cfg = self.cfg
        problem: str | None = None
        shown = units
        style: dict[str, Any] = {}
        if candidates is not None:
            shown = candidate_units(candidates, units, cfg.reduce_excerpt_chars)
            style = {"system": REDUCE_SYSTEM, "note": REDUCE_NOTE, "mark": CANDIDATES_MARK}
        for attempt in range(2 if target_s else 1):
            data, parts = await self._ask_parsed(
                shown, chapters, meta, instruction, target_s, problem=problem, **style
            )
            if candidates is not None:
                parts = expand_candidate_parts(parts, candidates, units)
            if not target_s:
                return data, parts
            chosen, total_s = select_for_target(parts, units, cfg, target_s)
            low, high = target_band(target_s, cfg.length_tolerance)
            if total_s >= low:
                return data, chosen
            if attempt == 0:
                events.emit(STAGE_MODEL, events.WARN, problem="below target length", retry=1)
                problem = (
                    f"it keeps only {int(total_s)} s in total but the task needs about "
                    f"{target_s} s (between {int(low)} and {int(high)} s); keep more parts."
                )
        raise CutRefused(
            f"The model kept only {int(total_s)} s of the {target_s} s this cut aims for, "
            "so no cut was built. Try again."
        )

    async def _ask_parsed(
        self,
        shown: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        *,
        problem: str | None = None,
        allow_empty: bool = False,
        **style: Any,
    ) -> tuple[Any, list[Part]]:
        """One question and its parsed answer; a broken answer gets one repair round."""
        data = await self._ask(
            shown, chapters, meta, instruction, target_s, problem=problem, **style
        )
        try:
            return data, parse_cut_answer(data, shown, allow_empty=allow_empty)
        except CutFormatError as exc:
            events.emit(STAGE_MODEL, events.WARN, problem=exc.problem, repair=1)
            data = await self._ask(
                shown, chapters, meta, instruction, target_s, problem=exc.problem, **style
            )
            try:
                return data, parse_cut_answer(data, shown, allow_empty=allow_empty)
            except CutFormatError as exc2:
                raise CutRefused(
                    f"The model's answer stayed unusable ({exc2.problem}), so no cut was built."
                ) from exc2

    def _tokens(self, message: str) -> int:
        return len(message) // self.cfg.chars_per_token

    def fits(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
    ) -> bool:
        """Whether the whole transcript goes to the model in one request."""
        message = serialize_units(
            units, chapters, meta, instruction, target_s, self.cfg.over_ask_frac
        )
        return self._tokens(message) <= self.cfg.max_input_tokens

    async def _all(self, jobs: list[Any]) -> list[Any]:
        """Run the coroutines together; the first failure cancels the rest and is raised."""
        tasks = [asyncio.ensure_future(job) for job in jobs]
        try:
            await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [task.result() for task in tasks]

    async def _map_reduce(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
    ) -> tuple[Any, list[Part]]:
        """A cut for a transcript too long for one request.

        Map: excerpts (on chapter boundaries when there are chapters, a few units shared with
        the previous one) are each asked for ranked candidate parts, with the excerpt's share of
        the target length. Reduce: one call over the candidates picks the cut, with the same
        rank selection as a one-pass cut; candidates that do not fit one call are narrowed in
        rounds first."""
        cfg = self.cfg
        chunks = self._plan_chunks(units, chapters, meta, instruction, target_s)
        total_s = sum(u.end - u.start for u in units) or 1.0
        gate = asyncio.Semaphore(cfg.map_parallel)
        proposed: list[list[Part]] = [[] for _ in chunks]
        done = 0

        async def one(chunk: Chunk) -> None:
            nonlocal done
            core_s = sum(u.end - u.start for u in chunk.core)
            share = max(1, round(target_s * core_s / total_s)) if target_s else None
            async with gate:
                proposed[chunk.index] = await self._map_chunk(
                    chunk, len(chunks), chapters, meta, instruction, share
                )
            done += 1
            events.emit(STAGE_MAP, events.RUNNING, done=done, of=len(chunks))

        with events.stage(STAGE_MAP, chunks=len(chunks), units=len(units)) as map_stage:
            events.emit(STAGE_MAP, events.RUNNING, done=0, of=len(chunks))
            await self._all([one(chunk) for chunk in chunks])
            cands = merge_candidates([c for parts in proposed for c in candidates_from(parts)])
            map_stage.set(candidates=len(cands))
        if not cands:
            raise CutRefused("Nothing was worth keeping, so there is no cut.")
        return await self._reduce(cands, units, chapters, meta, instruction, target_s)

    def _plan_chunks(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
    ) -> list[Chunk]:
        cfg = self.cfg
        header = serialize_units(
            [],
            chapters,
            meta,
            instruction,
            target_s,
            cfg.over_ask_frac,
            note=MAP_NOTE.format(i=99, n=99),
        )
        tokens = min(cfg.map_chunk_tokens, cfg.max_input_tokens)
        budget = tokens * cfg.chars_per_token - len(header) - len(CUT_SYSTEM)
        return plan_chunks(units, chapters, budget, cfg.map_overlap_units)

    async def _map_chunk(
        self,
        chunk: Chunk,
        n: int,
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        share: int | None,
    ) -> list[Part]:
        """Candidate parts of one excerpt; a failed excerpt is asked once more, then the cut fails."""
        note = MAP_NOTE.format(i=chunk.index + 1, n=n)
        span = chapters_between(chapters, chunk.units[0].start, chunk.units[-1].end)
        problem = ""
        for attempt in range(MAP_RETRIES + 1):
            try:
                _data, parts = await self._ask_parsed(
                    chunk.units,
                    span,
                    meta,
                    instruction,
                    share,
                    allow_empty=True,
                    note=note,
                    scope="from this excerpt",
                )
                return parts
            except CutRefused as exc:
                problem = exc.message
            except LLMError:
                log.warning("cut excerpt %d of %d: the model service failed", chunk.index + 1, n)
                problem = "the model service did not answer"
            events.emit(
                STAGE_MAP, events.WARN, excerpt=chunk.index + 1, problem=problem, retry=attempt + 1
            )
        raise CutRefused(
            f"Part {chunk.index + 1} of {n} of this long video could not be analysed "
            f"({problem.rstrip('.')}), so no cut was built. Try again."
        )

    async def _reduce(
        self,
        cands: list[Candidate],
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
    ) -> tuple[Any, list[Part]]:
        """The final choice over the candidates; too many for one call are narrowed in rounds."""
        cfg = self.cfg
        rounds = 0
        while True:
            shown = candidate_units(cands, units, cfg.reduce_excerpt_chars)
            message = serialize_units(
                shown, chapters, meta, instruction, target_s, cfg.over_ask_frac,
                note=REDUCE_NOTE, mark=CANDIDATES_MARK,
            )  # fmt: skip
            if self._tokens(message) <= cfg.max_input_tokens:
                with events.stage(STAGE_REDUCE, candidates=len(cands), rounds=rounds):
                    return await self._ask_parts(
                        units, chapters, meta, instruction, target_s, candidates=cands
                    )
            if rounds >= cfg.max_reduce_rounds:
                raise CutRefused(
                    "This video gave too many candidate parts to choose from, so no cut was built."
                )
            rounds += 1
            narrowed = await self._reduce_round(
                cands, units, chapters, meta, instruction, target_s, rounds
            )
            if not narrowed:
                raise CutRefused("Nothing was worth keeping, so there is no cut.")
            if len(narrowed) >= len(cands):
                raise CutRefused(
                    "The candidate parts could not be narrowed down, so no cut was built."
                )
            cands = narrowed

    async def _reduce_round(
        self,
        cands: list[Candidate],
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        round_no: int,
    ) -> list[Candidate]:
        """One narrowing round: groups of candidates that fit a call each keep their best parts
        (with a target: the group's share of it, plus the usual over-ask)."""
        cfg = self.cfg
        header = serialize_units(
            [], chapters, meta, instruction, target_s, cfg.over_ask_frac,
            note=REDUCE_NOTE, mark=CANDIDATES_MARK,
        )  # fmt: skip
        budget = cfg.max_input_tokens * cfg.chars_per_token - len(header) - len(REDUCE_SYSTEM)
        groups = split_candidates(cands, units, budget, cfg.reduce_excerpt_chars)
        spans = [sum(units[c.last - 1].end - units[c.first - 1].start for c in g) for g in groups]
        gate = asyncio.Semaphore(cfg.map_parallel)

        async def one(group: list[Candidate], span_s: float) -> list[Candidate]:
            share = max(1, round(target_s * span_s / (sum(spans) or 1.0))) if target_s else None
            shown = candidate_units(group, units, cfg.reduce_excerpt_chars)
            async with gate:
                _data, parts = await self._ask_parsed(
                    shown, chapters, meta, instruction, share,
                    allow_empty=True, system=REDUCE_SYSTEM, note=REDUCE_NOTE,
                    mark=CANDIDATES_MARK,
                )  # fmt: skip
            kept = expand_candidate_parts(parts, group, units)
            if share and kept:
                kept, _ = select_for_target(kept, units, cfg, int(share * (1 + cfg.over_ask_frac)))
            return candidates_from(kept)

        with events.stage(STAGE_REDUCE, candidates=len(cands), groups=len(groups), round=round_no):
            kept = await self._all([one(g, sp) for g, sp in zip(groups, spans, strict=True)])
        return merge_candidates([c for group in kept for c in group])

    async def _ask(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None = None,
        *,
        problem: str | None = None,
        system: str = CUT_SYSTEM,
        note: str | None = None,
        scope: str = "in total",
        mark: str = UNITS_MARK,
    ) -> Any:
        """The model's parsed answer. One repair round when the ids break the rules."""
        task = self.task()
        if task is None:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        message = serialize_units(
            units,
            chapters,
            meta,
            instruction,
            target_s,
            self.cfg.over_ask_frac,
            note=note,
            scope=scope,
            mark=mark,
        )
        if self._tokens(message) > self.cfg.max_input_tokens:
            raise CutRefused(
                "This video is too long to cut: a request does not fit the model's input "
                "even after splitting it up."
            )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": message},
        ]
        if problem:
            messages.append(
                {
                    "role": "user",
                    "content": f"Your previous answer was rejected: {problem} {CUT_JSON_RULES}",
                }
            )
        return await self.llm.chat_json(task, messages, priority=INTERACTIVE)
