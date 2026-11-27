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

from .auth import Auth
from .captions import events
from .captions.jobs import JobQueue
from .classes import NORMAL, PRIME, bind_class, highest, normalize_class, unbind_class
from .config import WATCHED_MODES, Config, CutsConfig, LLMTask
from .db import (
    MAX_CHANNEL_ID_CHARS,
    MAX_CHANNEL_NAME_CHARS,
    MODE_RULE_CHANNEL,
    MODE_RULE_REQUEST,
    MODE_RULE_SERVER,
    MODE_RULE_USER,
    Database,
)
from .feature import feature_run
from .inbox import KIND_CUT, InboxService, thumbnail_for
from .llm import INTERACTIVE, LLMClient, LLMError
from .media_archive import MediaArchive
from .prompts import CUT_PRESET_INSTRUCTIONS, Prompt, PromptStore
from .transcripts import (
    CAPTION_MANUAL,
    ROLLING_MIN_WORDS,
    SOURCE_ASR,
    Transcript,
    TranscriptService,
    fmt_ts,
)
from .usage import METRIC_YOUTUBE_FORBIDDEN
from .youtube import YoutubeGate

log = logging.getLogger("utubot.cuts")

# Stages this feature writes into the job report (the captions pipeline writes the others).
STAGE_TRANSCRIPT = "transcript"
STAGE_MODEL = "model"
STAGE_CHECKING = "checking"
STAGE_MAP = "map"  # long videos: excerpt i of n (detail `done`, `of`)
STAGE_REDUCE = "reduce"  # long videos: the final choice over the candidates (detail `round`)

# Shown on the TV when a cut cannot fetch the transcript because YouTube refused the download: the
# server waits for the TV's own captions (the client proxy path) instead of failing the cut.
FORBIDDEN_CAPTIONS_MESSAGE = (
    "YouTube refused the server and no captions are stored for this video. "
    "Play the video on the TV for a few seconds so it can send its captions; this cut then builds."
)

REQUEST_STATES = ("waiting", "building", "needs_transcript", "ready", "failed", "dismissed")
BUILDING_STATES = ("building", "needs_transcript")
QUEUE_LIMIT = 100
CUT_DOC_VERSION = 1
# Stored cuts remember the algorithm that built them. A repair only rebuilds cuts older than
# this, so a rebuilt cut that legitimately keeps a high share is not queued again on every start.
CUT_BUILD_VERSION = 2
# Marker of "superseded by a repair" rows: they leave the queue like a dismissed request.
REPAIR_MESSAGE = "This cut kept almost the whole video on a long video; it was rebuilt."

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
    "cut-skim-film": "Skim the film",
}
# A film-length cut: keeps the story beats and best scenes to a fraction of the runtime
# (`cuts.preset_target_frac`), scene-aware. Its target scales with the video, so it is meant
# for long films; a short video that already fits the band is cut without a target.
CUT_SKIM_FILM_PRESET_ID = "cut-skim-film"
# Removal presets keep whatever the video has left worth keeping; keeping nearly all of it is a
# valid result ("little or no filler"), so a named preset has no upper keep guard. Only the broad
# no-filler preset has the lower guard; a targeted answer or demo may legitimately be short.
REMOVAL_PRESET_IDS = frozenset({"cut-no-filler", "cut-answer", "cut-demo"})
NO_FILLER_PRESET_ID = "cut-no-filler"


def source_ref(row: dict[str, Any]) -> dict[str, Any]:
    """The one reader of the source columns: a row's source, its release and its cache source.

    Old rows have no source_key: they mean `youtube:<video_id>`, and their cache source stays the
    video id byte-for-byte. Other sources use `source_key|release_key` where a video id stands.
    """
    video_id = row.get("video_id")
    kind = row.get("source_kind") or "youtube"
    key = row.get("source_key") or f"youtube:{video_id}"
    release_key = row.get("release_key")
    release_duration_ms = row.get("release_duration_ms")
    youtube = kind == "youtube" and key.startswith("youtube:")
    return {
        "kind": kind,
        "key": key,
        "release_key": release_key,
        "release_duration_ms": release_duration_ms,
        "cache_source": video_id if youtube else f"{key}|{release_key or ''}",
    }


def source_document(ref: dict[str, Any]) -> dict[str, Any] | None:
    """The optional cut-document `source` object; absent means the YouTube video id as today."""
    if ref["kind"] == "youtube":
        return None
    source = {"kind": ref["kind"], "key": ref["key"]}
    if ref["release_key"] is not None:
        source["release_key"] = ref["release_key"]
    if ref["release_duration_ms"] is not None:
        source["release_duration_ms"] = ref["release_duration_ms"]
    return source


def source_matches(left: dict[str, Any], right: dict[str, Any], tolerance_ms: int) -> bool:
    """Same source and release, and a length within the configured tolerance."""
    if left["key"] != right["key"]:
        return False
    if left.get("release_key") or right.get("release_key"):
        if left.get("release_key") != right.get("release_key"):
            return False
    a, b = left.get("release_duration_ms"), right.get("release_duration_ms")
    if a is None or b is None:
        return True
    return abs(a - b) <= tolerance_ms


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


ClassSource = str | Callable[[], str]


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
    "parts stay in video order. Keep only candidates the task asks to keep: drop candidates that "
    "are merely content, context or filler, and prefer the task's own definition of the cut over "
    "completeness. When the task gives a target length or a maximum, add "
    '"rank":<int> to every part (1 = the most important part, every part its own number). '
    "Each candidate shows its rank inside its own excerpt; ranks of different excerpts are not "
    "comparable, so judge by the label and the text. Be faithful to the candidates; never "
    "invent content and never add commentary."
)
MAP_NOTE = (
    "This is excerpt {i} of {n} of a long video that is read in pieces; neighbouring excerpts "
    "share a few units. Apply the task to THIS excerpt: propose the parts it asks to keep, as if "
    "you were cutting this excerpt on its own, and leave out what it asks to cut. A later step "
    "merges the excerpts' choices and makes the final cut, so give every part a rank (1 = the "
    "best fit for the task in this excerpt, every part its own number) and answer "
    '{{"parts":[]}} when nothing here fits.'
)
REDUCE_NOTE = (
    "The video is long, so it was read in excerpts. The lines below are CANDIDATE parts the "
    "excerpts proposed, not transcript units: each shows its id, time range, label, its rank "
    "inside its own excerpt and a short text excerpt. Choose the candidates to keep; keep only "
    "the ones the task asks for and drop the rest. Each part you return is one candidate (from "
    "and to are the same id)."
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


def _drop_rolling_repeat(text: str, previous: str, min_words: int = ROLLING_MIN_WORDS) -> str:
    """A caption rolling window repeats the tail of the previous fragment at the start of this
    one; only that repeated run is dropped, like `transcripts.parse_json3_words` does."""
    words = text.split()
    previous_words = previous.split()
    for k in range(min(len(previous_words), len(words)), 0, -1):
        if k >= min_words and previous_words[-k:] == words[:k]:
            return " ".join(words[k:])
    return text


def _ends_sentence(text: str) -> bool:
    """A sentence end character ends a unit, also when a quote or bracket closes the sentence."""
    return text.rstrip(" '\"”’)]}」』").endswith(tuple(SENTENCE_END))


def build_units(
    segments: list[tuple[float, float, str]], cfg, *, rolling: bool = True
) -> list[Unit]:
    """Merge caption fragments into sentence-like units: a new unit starts on a pause over
    `cuts.unit_max_pause_s` or after sentence punctuation, and a unit never grows past
    `cuts.unit_max_s`. With `rolling` (YouTube's automatic captions) a fragment repeating the
    previous one's tail loses that repeat; an authored caption or ASR text keeps a genuine
    repetition (the same words said twice)."""
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
    prev_raw = ""
    for index, (seg_start, _seg_end, raw) in enumerate(segments):
        text = _clean_text(raw)
        if not text:
            continue
        raw_text = text
        seg_end = _effective_end(index, segments)
        pause = 0.0 if prev_end is None else seg_start - prev_end
        too_long = start is not None and seg_end - start > max_len
        after_pause = False
        if parts and (pause > max_pause or too_long or _ends_sentence(prev_text)):
            # A pause keeps a repeated line (live or edited speech); a sentence or length
            # boundary is a rolling caption window, so the repeated tail goes with it.
            after_pause = pause > max_pause
            flush()
        if rolling:
            if parts:
                text = _drop_rolling_repeat(text, prev_raw)
            elif not after_pause:
                # The first fragment after a sentence/length flush still repeats the previous
                # fragment; a one-word repeat ("Done.") is possible at that boundary.
                text = _drop_rolling_repeat(text, prev_raw, min_words=1)
        if not text:
            prev_end = max(seg_end, prev_end or 0.0)
            prev_raw = raw_text
            continue
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
            prev_raw = prev_text or raw_text
            continue
        if start is None:
            start = seg_start
        end = max(seg_end, start)
        parts.append(text)
        prev_end = max(seg_end, prev_end or 0.0)
        prev_text = text
        prev_raw = raw_text
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
    cap_s: int | None = None,
    note: str | None = None,
    scope: str = "in total",
    mark: str = UNITS_MARK,
) -> str:
    """The user message the cut model answers: the video facts, the task, then the numbered units.

    `note` is an extra paragraph after the task (map/reduce says which excerpt this is), `scope`
    what the target length counts ("in total", or "from this excerpt"), `mark` the line that
    introduces the numbered lines. `cap_s` is a maximum (not a goal) for a cut with no target."""
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
    elif cap_s:
        lines.append(
            f"Maximum length: at most {cap_s} s kept {scope}. Keep only what the task asks "
            "for, and give every part a rank (1 = most important): the server drops the "
            "lowest-ranked parts beyond that maximum."
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
    r"\s*(?:of (?:it|the video)\b|as long\b|long\b|version\b|shorter\b|total\b"
    r"|(?:of )?(?:the |its )?(?:original |full |whole |video'?s? )?"
    r"(?:size|length|duration|runtime|running time)\b)"
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
    if target_s is None and duration_s:
        frac = cfg.preset_target_frac.get(preset_id or "")
        if frac:
            target_s = int(round(duration_s * frac))
    if target_s is None:
        target_s = length_target_s(length, duration_s)
    if target_s is None:
        return None
    if duration_s and duration_s <= target_band(target_s, cfg.length_tolerance)[1]:
        return None
    return target_s


def _duration_ms(duration_s: float | None) -> int | None:
    return int(duration_s * 1000) if duration_s else None


def _final_bounds(part: Part, cfg, duration_ms: int | None) -> tuple[int, int]:
    """The padded boundaries of a kept part, clamped to the video."""
    start = max(0, part.start_ms - int(cfg.pad_before_s * 1000))
    end = part.end_ms + int(cfg.pad_after_s * 1000)
    if duration_ms is not None:
        end = min(end, duration_ms)
    return start, end


def _clamped_s(part: Part, duration_s: float | None = None) -> float:
    """The part on the model's boundaries, after clamping its end to the video."""
    duration_ms = _duration_ms(duration_s)
    end_ms = part.end_ms if duration_ms is None else min(part.end_ms, duration_ms)
    return max(0, end_ms - part.start_ms) / 1000.0


def _padded_s(part: Part, cfg, duration_s: float | None = None) -> float:
    """The length the finished cut will have: padding added and clamped to the video."""
    duration_ms = _duration_ms(duration_s)
    start, end = _final_bounds(part, cfg, duration_ms)
    return max(0, end - start) / 1000.0


def _kept_total_s(parts: list[Part], cfg, duration_s: float | None) -> float:
    """The length the finished cut will keep: merge, short-drop and padding applied like
    `finalize_parts`. Selection charges the merged gaps too, so it stops at the target only when
    the cut it counts is the cut that finalizes (and a merged gap cannot push it past the band)."""
    merged: list[Part] = []
    for part in sorted(parts, key=lambda p: p.start_ms):
        if merged and (part.start_ms - merged[-1].end_ms) < cfg.merge_gap_s * 1000:
            merged[-1] = Part(merged[-1].label, merged[-1].start_ms, part.end_ms)
        else:
            merged.append(Part(part.label, part.start_ms, part.end_ms))
    duration_ms = _duration_ms(duration_s)
    total = 0.0
    for part in merged:
        if _clamped_s(part, duration_s) < cfg.min_part_s:
            continue
        start, end = _final_bounds(part, cfg, duration_ms)
        total += max(0, end - start) / 1000.0
    return total


def _trim_to(
    part: Part,
    units: list[Unit],
    budget_s: float,
    cfg,
    duration_s: float | None = None,
    chosen: list[Part] | None = None,
) -> Part | None:
    """The leading units of `part` that fit `budget_s` (padding included), cut at a unit
    boundary; None when not even the first unit fits, the part has no unit ids, or the trim
    would fall under `min_part_s` on its clamped boundaries. `chosen` (parts already kept)
    makes the budget the part's increase once merged with them, so a part that would bridge a
    sub-gap past the budget is trimmed to fit instead of dropped whole."""
    if part.first is None or part.last is None:
        return None
    chosen = chosen or []
    base = _kept_total_s(chosen, cfg, duration_s)
    trimmed = None
    for n in range(part.first, part.last + 1):
        candidate = Part(
            part.label,
            part.start_ms,
            int(units[n - 1].end * 1000),
            part.rank,
            part.first,
            n,
        )
        if _kept_total_s(chosen + [candidate], cfg, duration_s) - base > budget_s:
            break
        trimmed = candidate
    if trimmed is None or _clamped_s(trimmed, duration_s) < cfg.min_part_s:
        return None
    return trimmed


def _rank_order(parts: list[Part]) -> list[int]:
    """Part indexes by importance: rank ascending, unranked parts after the ranked ones."""
    return sorted(
        range(len(parts)),
        key=lambda i: (parts[i].rank if parts[i].rank is not None else len(parts) + i + 1, i),
    )


def ranked_tail_in_time_order(parts: list[Part]) -> int:
    """How many of the lowest-ranked parts follow video order (the model numbered them as it
    read, instead of judging them); 0 or 1 for an answer that really ranks."""
    order = _rank_order(parts)
    count = 1 if order else 0
    for k in range(len(order) - 1, 0, -1):
        before, after = parts[order[k - 1]], parts[order[k]]
        if before.rank is None or after.rank is None or before.rank >= after.rank:
            break  # tied or missing ranks are not a judgement either way
        if before.start_ms < after.start_ms:
            count += 1
        else:
            break
    return count


def is_non_selection(parts: list[Part], cfg, budget_s: float, duration_s: float | None) -> bool:
    """Whether the answer ranks (almost) everything instead of choosing: it keeps far more than
    the target or maximum, or its ranks follow video order over a long tail while it is over the
    asked amount plus the band. A normal answer (a little over the target, really ranked) is neither."""
    if not parts or budget_s <= 0:
        return False
    total = _kept_total_s(parts, cfg, duration_s)
    if total > budget_s * cfg.non_selection_factor:
        return True
    asked_s = budget_s * (1 + cfg.over_ask_frac + cfg.length_tolerance)
    return total > asked_s and ranked_tail_in_time_order(parts) >= cfg.rank_tail_min


def choose_problem(parts: list[Part], cfg, budget_s: int, duration_s: float | None) -> str | None:
    """The re-ask text for a non-selection answer, or None when the answer chose."""
    if not is_non_selection(parts, cfg, budget_s, duration_s):
        return None
    total = int(_kept_total_s(parts, cfg, duration_s))
    return (
        f"it keeps {total} s, nearly the whole video, and its ranks follow video order, so "
        f"nothing was chosen. Choose about {budget_s} s ({max(1, round(budget_s / 60))} min) of "
        "the best parts from everything shown, leave everything else out, and rank only the parts "
        "you keep by importance (rank 1 = the most important, not the earliest)."
    )


def spread_select(
    parts: list[Part],
    units: list[Unit],
    cfg,
    budget_s: float,
    duration_s: float | None = None,
) -> list[Part]:
    """The parts of a non-selection answer that fit `budget_s`, spread over the video.

    The video is split into windows of half `max_skip_s`; each window keeps its share of the
    budget (its share of the answer's own length, carrying what earlier windows left unspent),
    taking its parts by rank and trimming the one that crosses its share. So no stretch this trim
    removes is longer than `max_skip_s`, whatever order the ranks have."""
    eligible = [p for p in parts if _clamped_s(p, duration_s) >= cfg.min_part_s]
    if not eligible:
        return []
    width_ms = max(1, int(cfg.max_skip_s * 500))
    windows: dict[int, list[Part]] = {}
    for part in eligible:
        windows.setdefault(part.start_ms // width_ms, []).append(part)
    pool_left = sum(_padded_s(p, cfg, duration_s) for p in eligible)
    floor_s = cfg.min_part_s + cfg.pad_before_s + cfg.pad_after_s
    chosen: list[Part] = []
    spent = 0.0
    for key in sorted(windows):
        members = windows[key]
        pool_s = sum(_padded_s(p, cfg, duration_s) for p in members)
        quota = max(floor_s, (budget_s - spent) * pool_s / pool_left) if pool_left else 0.0
        pool_left -= pool_s
        mine: list[Part] = []
        taken = 0.0
        for i in _rank_order(members):
            if taken >= quota:
                break
            part = members[i]
            if _kept_total_s(mine + [part], cfg, duration_s) > quota:
                part = _trim_to(part, units, quota - taken, cfg, duration_s, mine)
                if part is None:
                    continue
            mine.append(part)
            taken = _kept_total_s(mine, cfg, duration_s)
        chosen.extend(mine)
        spent += taken
    return chosen


def select_for_target(
    parts: list[Part],
    units: list[Unit],
    cfg,
    target_s: int,
    duration_s: float | None = None,
) -> tuple[list[Part], float]:
    """Pick parts by importance until the target is met; `(parts in video order, length in s)`.

    Parts are taken by rank (parts without one count in video order, after the ranked ones).
    A part that would push the total past the band is trimmed at a unit boundary to fit; the
    selection stops once the merged, padded length reaches the target. Parts under `min_part_s`
    on their clamped boundaries are never selected (padding does not make them keepable), so the
    same parts survive `finalize_parts`. The stop and trim charge a part's increase once merged
    with what is kept (the same merge, short-drop and padding rules as `finalize_parts`), so a
    sub-gap cannot pull filler in and push the cut past the accepted band. A model answer shorter
    than the band returns its keepable parts, so the caller can see the shortfall.
    """
    low, high = target_band(target_s, cfg.length_tolerance)
    eligible = [i for i, part in enumerate(parts) if _clamped_s(part, duration_s) >= cfg.min_part_s]
    pool_s = _kept_total_s([parts[i] for i in eligible], cfg, duration_s)
    if pool_s < low:
        return [parts[i] for i in eligible], pool_s
    if is_non_selection(parts, cfg, target_s, duration_s):
        chosen = sorted(
            spread_select(parts, units, cfg, target_s, duration_s), key=lambda p: p.start_ms
        )
        return chosen, _kept_total_s(chosen, cfg, duration_s)
    order = [i for i in _rank_order(parts) if i in set(eligible)]
    chosen: list[Part] = []
    total = 0.0
    for i in order:
        if total >= target_s:
            break
        part = parts[i]
        if _kept_total_s(chosen + [part], cfg, duration_s) > high:
            trimmed = _trim_to(part, units, high - total, cfg, duration_s, chosen)
            if trimmed is None:
                continue
            part = trimmed
        chosen.append(part)
        total = _kept_total_s(chosen, cfg, duration_s)
    chosen.sort(key=lambda p: p.start_ms)
    return chosen, total


def trim_to_cap(
    parts: list[Part], units: list[Unit], cfg, cap_s: int, duration_s: float | None = None
) -> list[Part]:
    """The highest-ranked parts of a no-target cut that fit `cap_s`, in video order.

    A cap never adds parts beyond the model's answer: it keeps the ranked parts while they fit
    and trims the one that crosses the maximum at a unit boundary. A single part always
    survives, so a one-part answer is trimmed rather than dropped; the caller still checks it.
    """
    if sum(_padded_s(p, cfg, duration_s) for p in parts) <= cap_s or not parts:
        return list(parts)
    if is_non_selection(parts, cfg, cap_s, duration_s):
        spread = spread_select(parts, units, cfg, cap_s, duration_s)
        if spread:
            return sorted(spread, key=lambda p: p.start_ms)
    chosen: list[Part] = []
    spent = 0.0
    for i in _rank_order(parts):
        if spent >= cap_s:
            break
        part = parts[i]
        remaining = cap_s - spent
        length = _padded_s(part, cfg, duration_s)
        if length <= remaining:
            chosen.append(part)
            spent += length
            continue
        trimmed = _trim_to(part, units, remaining, cfg, duration_s)
        if trimmed is not None:
            chosen.append(trimmed)
            spent += _padded_s(trimmed, cfg, duration_s)
    if not chosen:
        chosen = [parts[_rank_order(parts)[0]]]
    chosen.sort(key=lambda p: p.start_ms)
    return chosen


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


def keep_guards(cfg, preset_id: str | None, target_s: int | None) -> tuple[bool, bool]:
    """(guard, guard_max) of a request: whether keeping too little and keeping too much refuse.

    A length-targeted cut defers to its band, and presets that keep a small part by design
    (`cuts.short_presets`, the highlights) are never refused as "removes almost everything". A
    named preset is a deliberate removal instruction, so keeping nearly all of the video is a
    result, not "nothing to cut"; only a typed prompt keeps the upper guard.
    """
    preset = preset_id or ""
    guard = (
        target_s is None and not preset.endswith("highlights-5") and preset not in cfg.short_presets
    )
    return guard, guard and preset_id is None


def finalize_parts(
    parts: list[Part],
    cfg,
    *,
    guard: bool,
    duration_s: float | None,
    guard_max: bool | None = None,
) -> tuple[list[Part], float | None]:
    """Merge and drop the kept parts, then pad their boundaries; check how much survives.

    Gaps under `cuts.merge_gap_s` are merged first, so padding cannot pull a dropped gap into a
    merge. Parts under `cuts.min_part_s` are then dropped on the model's boundaries clamped to
    the video (a part ending past the video can shrink under the minimum), before any padding,
    so padding cannot keep a part the model made too short. Only the kept boundaries are padded
    `pad_before_s`/`pad_after_s`. A cut keeping under `min_keep_frac` ("this would remove almost
    everything") is refused while `guard` is on. A cut over `max_keep_frac` ("nothing to cut") is
    refused only while `guard_max` is on (it defaults to `guard`).
    """
    merged: list[Part] = []
    for part in parts:
        if merged and (part.start_ms - merged[-1].end_ms) < cfg.merge_gap_s * 1000:
            merged[-1] = Part(merged[-1].label, merged[-1].start_ms, part.end_ms)
        else:
            merged.append(Part(part.label, part.start_ms, part.end_ms))
    duration_ms = _duration_ms(duration_s)
    kept: list[Part] = []
    for part in merged:
        if _clamped_s(part, duration_s) < cfg.min_part_s:
            continue
        start, end = _final_bounds(part, cfg, duration_ms)
        kept.append(Part(part.label, start, end))
    if not kept:
        raise CutRefused("Nothing was worth keeping, so there is no cut.")
    kept_ms = sum(p.end_ms - p.start_ms for p in kept)
    if duration_s:
        duration_ms = int(duration_s * 1000)
        frac = kept_ms / duration_ms
        if guard and frac < cfg.min_keep_frac:
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
    source: str,
    preset_id: str | None,
    built_at: float | None = None,
    target_s: int | None = None,
    transitions: list[dict[str, Any]] | None = None,
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
        "source": source,
        "preset_id": preset_id,
        "model": model,
        "mode": "quick",
        "built_at": built_at or time.time(),
    }
    if transitions is not None:
        doc["transitions"] = transitions
    return doc


def list_etag(entries: list[dict[str, Any]]) -> str:
    """A strong ETag for a cut list state: it changes whenever anything the menu shows changes (a preset's
    state, a ready cut, the selection, the modes), so a re-validating client gets 304 only when nothing moved."""
    blob = "|".join(json.dumps(entry, sort_keys=True, separators=(",", ":")) for entry in entries)
    return '"' + hashlib.sha256(blob.encode()).hexdigest()[:32] + '"'


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
        auth: Auth | None = None,
        archive: MediaArchive | None = None,
        gate: YoutubeGate | None = None,
        inbox: InboxService | None = None,
    ):
        self.cfg, self.db, self.llm = cfg, db, llm
        self.transcripts, self.prompts, self.jobs = transcripts, prompts, jobs
        self.auth, self.archive, self.gate = auth, archive, gate
        self.inbox = inbox
        self._watched_running = 0
        self._user_running: dict[str, int] = {}
        # Whether the build that holds the single watched slot for a request currently holds it:
        # a normal build releases the slot while it yields to a prime build and re-acquires it, so
        # the release in `_build`'s finally must not double-count a slot that was given up.
        self._watched_held: dict[str, bool] = {}
        self.engine = CutEngine(cfg.cuts, lambda: cfg.llm.cuts, llm)
        self._tasks: dict[str, asyncio.Task] = {}
        # One build in flight per cache key: a second request with the same key waits on the
        # leader's future instead of calling the model again (shared builds, plan v2).
        self._inflight: dict[str, asyncio.Future[dict[str, Any]]] = {}
        # A shared build's class only rises: a prime request joining it makes the build prime,
        # a normal request never lowers or raises a build.
        self._build_class: dict[str, str] = {}
        # Cost and wall time of the last build per request id, for the cut document's cost line.
        self._run_cost: dict[str, tuple[float, float]] = {}

    def stored_tdt(self, video_id: str) -> dict[str, Any] | None:
        """The newest stored watched TDT for the admin job page; None when no description exists."""
        row = self.db.one(
            "SELECT * FROM scene_descriptions WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
            [video_id],
        )
        if row is None:
            return None
        try:
            payload = json.loads(row["json"])
        except ValueError:
            return {"error": "the stored TDT is not JSON", "cache_key": row["cache_key"]}
        return {"cache_key": row["cache_key"], "tdt": payload}

    def clear_watched_cache(self, video_id: str) -> dict[str, int]:
        """Drop watched scene/description/label rows with their media (the archive cleanup hook)."""
        desc_keys = [
            row["cache_key"]
            for row in self.db.all(
                "SELECT cache_key FROM scene_descriptions WHERE video_id=?", [video_id]
            )
        ]
        labels = 0
        for key in desc_keys:
            labels += self.db.execute_rc("DELETE FROM scene_labels WHERE descriptions_key=?", [key])
        scenes = self.db.execute_rc("DELETE FROM video_scenes WHERE video_id=?", [video_id])
        descriptions = self.db.execute_rc(
            "DELETE FROM scene_descriptions WHERE video_id=?", [video_id]
        )
        return {"scene_rows": scenes, "description_rows": descriptions, "label_rows": labels}

    # ---- configuration --------------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        return self.cfg.llm.cuts is not None

    @property
    def watched_available(self) -> tuple[bool, str | None]:
        from .watch import watched_available

        return watched_available(self.cfg)

    def presets(self, user: str) -> list[Prompt]:
        return self.prompts.cut_prompts(user)

    # ---- the viewer's choice --------------------------------------------------------------------

    def choose(
        self,
        user: str,
        video_id: str,
        *,
        preset: str | None = None,
        request: str | None = None,
        off: bool = False,
    ) -> None:
        """Remember what the viewer chose for this video, and the preset used last across videos.

        A preset or a request is one choice; `off` is the explicit choice to play uncut. The
        last-used preset is updated only by a preset choice, so a typed cut does not move it.
        """
        if preset is not None and request is not None:
            raise CutRefused("A cut choice is a preset or a request, not both.", status=400)
        if not off and preset is None and request is None:
            raise CutRefused("A cut choice needs a preset, a request or off.", status=400)
        if off and (preset is not None or request is not None):
            raise CutRefused("Turning the cut off names no preset or request.", status=400)

        if off:
            self.db.execute(
                "INSERT INTO cut_choices(user,video_id,preset_id,request_id,off,updated_at)"
                " VALUES(?,?,NULL,NULL,1,?) ON CONFLICT(user,video_id) DO UPDATE SET"
                " preset_id=NULL, request_id=NULL, off=1, updated_at=excluded.updated_at",
                [user, video_id, time.time()],
            )
            return

        if preset is not None:
            if not any(p.id == preset for p in self.presets(user)):
                raise CutRefused(f"Unknown cut preset {preset}.")
            self.db.execute(
                "INSERT INTO cut_choices(user,video_id,preset_id,request_id,off,updated_at)"
                " VALUES(?,?,?,NULL,0,?) ON CONFLICT(user,video_id) DO UPDATE SET"
                " preset_id=excluded.preset_id, request_id=NULL, off=0,"
                " updated_at=excluded.updated_at",
                [user, video_id, preset, time.time()],
            )
            self._remember_preset(user, preset)
            return

        row = self._row(request)  # type: ignore[arg-type]
        if row is None or row["user"] != user or row["video_id"] != video_id:
            raise CutRefused("No such cut request for this video.", status=404)
        self.db.execute(
            "INSERT INTO cut_choices(user,video_id,preset_id,request_id,off,updated_at)"
            " VALUES(?,?,?,?,0,?) ON CONFLICT(user,video_id) DO UPDATE SET"
            " preset_id=excluded.preset_id, request_id=excluded.request_id, off=0,"
            " updated_at=excluded.updated_at",
            [user, video_id, row["preset_id"], request, time.time()],
        )
        if row["preset_id"]:
            self._remember_preset(user, row["preset_id"])

    def _remember_request(self, row: dict[str, Any]) -> None:
        """A cut the viewer asked for (a preset or a typed description) is their choice for the video."""
        if row["preset_id"]:
            self.choose(row["user"], row["video_id"], preset=row["preset_id"])
        elif row["prompt"] is not None:
            self.choose(row["user"], row["video_id"], request=row["id"])

    def _remember_preset(self, user: str, preset: str) -> None:
        self.db.execute(
            "INSERT INTO cut_last_presets(user,preset_id,updated_at) VALUES(?,?,?)"
            " ON CONFLICT(user) DO UPDATE SET preset_id=excluded.preset_id,"
            " updated_at=excluded.updated_at",
            [user, preset, time.time()],
        )

    def _choice(self, user: str, video_id: str) -> dict[str, Any] | None:
        row = self.db.one("SELECT * FROM cut_choices WHERE user=? AND video_id=?", [user, video_id])
        return dict(row) if row else None

    def _last_preset(self, user: str) -> str | None:
        row = self.db.one("SELECT preset_id FROM cut_last_presets WHERE user=?", [user])
        return row["preset_id"] if row else None

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
        """Requests are recorded and wait their turn; only a runaway queue is refused."""
        if self.building_count(user) >= self.cfg.cuts.max_queued_per_user:
            raise CutRefused(
                f"You already have {self.cfg.cuts.max_queued_per_user} cuts waiting; "
                "this one was not recorded.",
                status=429,
            )

    async def _wait_for_prime(
        self,
        row: dict[str, Any],
        trace: events.JobTrace,
        klass: str | Callable[[], str] = NORMAL,
        *,
        release_slot_request_id: str | None = None,
    ) -> bool:
        """Pause a normal watched build while prime demanding work is queued or running.

        With `release_slot_request_id` the build holds the single watched-build slot while it
        waits: releasing it lets the prime build it yields to take that slot instead of blocking
        on it forever, and the build re-acquires the slot afterwards. Describing is resumable per
        grid (2.4), so the paused build continues at the next grid with the same stored TDT.
        """
        if (row.get("mode") or "quick") != "watched":
            return False
        job_id = row["job_id"]
        current = klass if callable(klass) else (lambda: klass)
        waited = False
        while normalize_class(current()) != PRIME and self.jobs.class_gate.prime_active(job_id):
            if not waited:
                if release_slot_request_id is not None:
                    self._release_watched(release_slot_request_id)
                trace.emit(
                    events.IN_LINE,
                    events.INFO,
                    reason="priority",
                    progress=self._job_progress(job_id),
                    message="Waiting for a priority job.",
                )
            waited = True
            await asyncio.sleep(self.jobs.class_gate.poll_s)
        if waited and release_slot_request_id is not None:
            if not self._dismissed(release_slot_request_id):
                await self._acquire_watched(release_slot_request_id, trace)
        return waited

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

    # ---- the queue ------------------------------------------------------------------------------

    def resolve_mode(self, user: str, mode: str | None, channel_id: str | None = None) -> str:
        """The request's mode: explicit, else the channel's, the user's, then the server's default."""
        return self.resolve_mode_rule(user, mode, channel_id)[0]

    def resolve_mode_rule(
        self, user: str, mode: str | None, channel_id: str | None = None
    ) -> tuple[str, str]:
        """The mode a request runs in and the rule that decided it.

        A channel, user or server default of watched on a server without it resolves to quick
        but still reports the rule that chose; an explicit watched request is refused with the
        server's plain reason.
        """
        if mode is not None and mode not in WATCHED_MODES:
            raise CutRefused(
                f"Unknown cut mode {mode}; use {', '.join(WATCHED_MODES)}.", status=400
            )
        from .watch import watched_not_configured

        reason = watched_not_configured(self.cfg)
        if mode is not None:
            if mode == "watched" and reason is not None:
                raise CutRefused(reason, status=409)
            return mode, MODE_RULE_REQUEST
        policy = None
        if self.auth is not None:
            user_cfg = self.auth.user_config(user)
            policy = user_cfg.policy.cut_mode if user_cfg is not None else None
        channel_mode = self._channel_mode_value(user, channel_id)
        for chosen, rule in (
            (channel_mode, MODE_RULE_CHANNEL),
            (policy, MODE_RULE_USER),
            (self.cfg.cuts.default_mode, MODE_RULE_SERVER),
        ):
            if not chosen:
                continue
            if chosen == "watched" and reason is not None:
                return "quick", rule
            return chosen, rule
        return "quick", MODE_RULE_SERVER

    # ---- channel defaults -----------------------------------------------------------------------

    @staticmethod
    def _clean_channel_id(channel_id: str | None) -> str | None:
        channel_id = (channel_id or "").strip()
        if len(channel_id) > MAX_CHANNEL_ID_CHARS:
            raise CutRefused(
                f"A channel id is at most {MAX_CHANNEL_ID_CHARS} characters.", status=400
            )
        return channel_id or None

    @staticmethod
    def _clean_channel_name(channel_name: str | None) -> str | None:
        channel_name = " ".join((channel_name or "").split())
        return channel_name[:MAX_CHANNEL_NAME_CHARS] or None

    def _video_channel(
        self, video_id: str, channel_id: str | None
    ) -> tuple[str | None, str | None]:
        """The video's channel id and name, from the request or the cached video facts."""
        meta = self._meta(video_id)
        found = self._clean_channel_id(channel_id) or self._clean_channel_id(meta.get("channel_id"))
        return found, self._clean_channel_name(meta.get("channel"))

    def _channel_mode_value(self, user: str, channel_id: str | None) -> str | None:
        channel_id = self._clean_channel_id(channel_id)
        if not channel_id:
            return None
        row = self.db.one(
            "SELECT mode FROM cut_channel_modes WHERE user=? AND channel_id=?", [user, channel_id]
        )
        return row["mode"] if row else None

    def channel_modes(self, user: str) -> list[dict[str, Any]]:
        """Every channel the owner has a default for or has cut, by name then id.

        A channel with no stored default has `mode: null`; the phone lists it so the owner can
        set one there without waiting for the TV.
        """
        rows = self.db.all(
            "SELECT channel_id, channel_name, mode, updated_at FROM cut_channel_modes WHERE user=?",
            [user],
        )
        channels = {row["channel_id"]: dict(row) for row in rows}
        seen = self.db.all(
            "SELECT DISTINCT video_id, channel_id FROM cut_requests WHERE user=?", [user]
        )
        for row in seen:
            meta = self._meta(row["video_id"])
            try:
                channel_id = self._clean_channel_id(row["channel_id"] or meta.get("channel_id"))
            except CutRefused:
                continue
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

    def set_channel_mode(
        self, user: str, channel_id: str, mode: str, channel_name: str | None = None
    ) -> dict[str, Any]:
        """Store the owner's default mode for a channel; `watched` must be configured."""
        channel_id = self._clean_channel_id(channel_id)
        if not channel_id:
            raise CutRefused("A channel id is required.", status=400)
        if mode not in WATCHED_MODES:
            raise CutRefused(
                f"Unknown cut mode {mode}; use {', '.join(WATCHED_MODES)}.", status=400
            )
        if mode == "watched":
            from .watch import watched_not_configured

            reason = watched_not_configured(self.cfg)
            if reason is not None:
                raise CutRefused(reason, status=409)
        channel_name = self._clean_channel_name(channel_name)
        if channel_name is None:
            row = self.db.one(
                "SELECT channel_name FROM cut_channel_modes WHERE user=? AND channel_id=?",
                [user, channel_id],
            )
            channel_name = row["channel_name"] if row else None
        now = time.time()
        self.db.execute(
            "INSERT INTO cut_channel_modes(user,channel_id,channel_name,mode,updated_at)"
            " VALUES(?,?,?,?,?) ON CONFLICT(user,channel_id) DO UPDATE SET"
            " channel_name=excluded.channel_name, mode=excluded.mode,"
            " updated_at=excluded.updated_at",
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
                "DELETE FROM cut_channel_modes WHERE user=? AND channel_id=?", [user, channel_id]
            )
            > 0
        )

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
        force: bool = False,
        refetch: bool = False,
        channel_id: str | None = None,
    ) -> dict[str, Any]:
        """Queue a cut. Exactly one of `preset` / `prompt`; `await_prompt` creates an empty
        request the phone fills later. An identical active request is returned as-is."""
        if not self.configured:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        channel_id, _ = self._video_channel(video_id, channel_id)
        chosen_mode, mode_rule = self.resolve_mode_rule(user, mode, channel_id)
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
            user, video_id, preset, prompt, await_prompt, chosen_mode, force, refetch
        )
        if existing is not None:
            if not await_prompt:
                self._remember_request(existing)
            return existing
        klass = self.jobs._class_for(user, None)
        if not await_prompt:
            self._check_cap(user)
        request_id = self._enqueue(
            user,
            video_id,
            source=source,
            preset=preset,
            prompt=prompt,
            await_prompt=await_prompt,
            mode=mode,
            force=force,
            refetch=refetch,
            klass=klass,
            channel_id=channel_id,
        )
        if not await_prompt:
            row = self._row(request_id)
            if row is not None:
                self._remember_request(row)
            self._start(request_id)
        return self._row(request_id)  # type: ignore[return-value]

    def _enqueue(
        self,
        user: str,
        video_id: str,
        *,
        source: str = "",
        preset: str | None = None,
        prompt: str | None = None,
        await_prompt: bool = False,
        mode: str | None = None,
        force: bool = False,
        refetch: bool = False,
        klass: str | None = None,
        message: str | None = None,
        channel_id: str | None = None,
    ) -> str:
        """Insert a request and its job row; the caller decides whether to start the build."""
        klass = klass or NORMAL
        request_id = uuid.uuid4().hex[:12]
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        title = self._meta(video_id).get("title")
        channel_id, _ = self._video_channel(video_id, channel_id)
        chosen_mode, mode_rule = self.resolve_mode_rule(user, mode, channel_id)
        self.db.execute(
            "INSERT INTO jobs(id,user,video_id,lang,translate_to,status,progress,created_at,"
            "updated_at,kind,title,priority,klass)"
            " VALUES(?,?,?,'',NULL,'queued',0,?,?, 'cuts',?,?,?)",
            [job_id, user, video_id, now, now, title, INTERACTIVE, klass],
        )
        self.db.execute(
            "INSERT INTO cut_requests(id,user,video_id,source,preset_id,prompt,state,job_id,"
            "created_at,updated_at,mode,source_kind,source_key,force,klass,mode_rule,channel_id,refetch)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                chosen_mode,
                "youtube",
                f"youtube:{video_id}",
                1 if force else 0,
                klass,
                mode_rule,
                channel_id,
                1 if refetch else 0,
            ],
        )
        origin = events.current_origin()
        detail: dict[str, Any] = {
            "kind": "cuts",
            "user": user,
            "class": klass,
            "client": source or (origin.client if origin else "server"),
            "endpoint": origin.endpoint if origin else None,
            "video_id": video_id,
            "title": title,
            "preset": preset,
            "prompt": prompt,
            "await_prompt": await_prompt,
            "mode": chosen_mode,
        }
        if message:
            detail["message"] = message
        self.jobs.events.record(
            job_id,
            events.QUEUED,
            events.OK,
            detail,
            ts=now,
        )
        return request_id

    def _active_same(
        self,
        user: str,
        video_id: str,
        preset: str | None,
        prompt: str | None,
        await_prompt: bool,
        mode: str = "quick",
        force: bool = False,
        refetch: bool = False,
    ) -> dict[str, Any] | None:
        """An active request for the same cut: a forced or refetching one never joins another kind."""
        states = (*BUILDING_STATES, "waiting")
        marks = ",".join("?" * len(states))
        where = (
            f"user=? AND video_id=? AND force=? AND mode=? AND state IN ({marks})"
            f" AND refetch={1 if refetch else 0}"
        )
        if await_prompt:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE {where} AND preset_id IS NULL"
                " AND prompt IS NULL ORDER BY created_at DESC LIMIT 1",
                [user, video_id, 1 if force else 0, mode, *states],
            )
        elif prompt is not None:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE {where} AND prompt=?"
                " ORDER BY created_at DESC LIMIT 1",
                [user, video_id, 1 if force else 0, mode, *states, prompt],
            )
        else:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE {where} AND preset_id=?"
                " ORDER BY created_at DESC LIMIT 1",
                [user, video_id, 1 if force else 0, mode, *states, preset],
            )
        return dict(row) if row else None

    def fill(
        self,
        request_id: str,
        user: str,
        prompt: str,
        mode: str | None = None,
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
        chosen_mode = row["mode"] or "quick"
        mode_rule = row["mode_rule"] or MODE_RULE_REQUEST
        stored_channel = row["channel_id"]
        if mode is not None:
            stored_channel, _ = self._video_channel(row["video_id"], channel_id or stored_channel)
            chosen_mode, mode_rule = self.resolve_mode_rule(user, mode, stored_channel)
        prompt = self._validate_prompt(prompt)
        if prompt is None:
            raise CutRefused("The description of the cut is empty.")
        self._check_cap(user)
        self.db.execute(
            "UPDATE cut_requests SET prompt=?, mode=?, mode_rule=?, channel_id=?,"
            " state='building', updated_at=? WHERE id=?",
            [prompt, chosen_mode, mode_rule, stored_channel, time.time(), request_id],
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
        self.choose(user, row["video_id"], request=request_id)
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
        # A preset request records its choice by preset (request_id is NULL), so both forms of the choice are
        # cleared here; a newer choice of another preset or request does not match and stays.
        self.db.execute(
            "DELETE FROM cut_choices WHERE user=? AND video_id=?"
            " AND (request_id=? OR (request_id IS NULL AND preset_id=?))",
            [user, row["video_id"], request_id, row["preset_id"]],
        )
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
            "preset_id": row["preset_id"],
            "prompt": row["prompt"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "mode": row["mode"] or "quick",
            "mode_rule": row["mode_rule"] or MODE_RULE_REQUEST,
            **{
                k: v
                for k, v in self._meta(row["video_id"]).items()
                if k in ("title", "channel", "duration_s")
            },
        }
        if row["channel_id"]:
            out["channel_id"] = row["channel_id"]
        if row["state"] in BUILDING_STATES and row["job_id"]:
            stage = self._last_stage(row["job_id"])
            out["stage"] = stage
            if (row["mode"] or "quick") == "watched":
                out["progress"] = float(row["progress"] or 0.0)
                out["eta_s"] = self._eta(row)
            else:
                progress = self._last_progress(row["job_id"])
                if progress:
                    out["progress"] = progress
            if stage == events.IN_LINE:
                out["reason"] = "priority"
                out["message"] = "Waiting for a priority job."
                done = self._job_progress(row["job_id"])
                if done is not None:
                    out["progress"] = done
        if row["state"] == "failed" and (row["mode"] or "quick") == "watched":
            out["fallback"] = self._fallback(row)
        if row["state"] == "ready" and row["cut_key"]:
            cut = self.db.one("SELECT json FROM cuts WHERE cache_key=?", [row["cut_key"]])
            if cut:
                out["cut"] = json.loads(cut["json"])
        cost = self._run_cost.get(row["id"])
        if cost is not None:
            out["cost_usd"] = round(cost[0], 5)
            out["elapsed_s"] = cost[1]
        return out

    def _eta(self, row: dict[str, Any]) -> int | None:
        """The estimate still ahead, from the duration and the progress the build writes."""
        meta = self._meta(row["video_id"])
        duration = float(meta.get("duration_s") or 0.0)
        if not duration:
            return None
        watched = self.cfg.cuts.watched
        minutes = duration / 60.0
        total = (
            watched.eta_s_per_grid * watched.eta_grids_per_minute * minutes
            + watched.eta_grid_stage_s_per_minute * minutes
            + watched.eta_fixed_s
        )
        done = float(row["progress"] or 0.0)
        return max(1, int(round(total * max(0.0, 1.0 - done))))

    def _fallback(self, row: dict[str, Any]) -> dict[str, Any]:
        """The Quick state of the same preset or description, for the one-press offer."""
        preset_id, prompt = row["preset_id"], row["prompt"]
        saved = (
            next((p for p in self.presets(row["user"]) if p.id == preset_id), None)
            if preset_id
            else None
        )
        fallback: dict[str, Any] = {"mode": "quick", "state": "none"}
        ready = (
            self._ready_cut(row["video_id"], saved or prompt, "quick")
            if (preset_id or prompt)
            else None
        )
        if ready is not None:
            fallback.update(state="ready", cut=ready)
            return fallback
        active = self.db.one(
            "SELECT id, state FROM cut_requests WHERE user=? AND video_id=? AND mode='quick'"
            + (
                " AND preset_id=? AND state IN ('waiting','building','needs_transcript')"
                if preset_id
                else " AND prompt=? AND state IN ('waiting','building','needs_transcript')"
            )
            + " ORDER BY created_at DESC LIMIT 1",
            [row["user"], row["video_id"], preset_id or prompt],
        )
        if active:
            fallback.update(state=active["state"], request_id=active["id"])
            return fallback
        failed = self.db.one(
            "SELECT id, error FROM cut_requests WHERE user=? AND video_id=? AND mode='quick'"
            + (" AND preset_id=?" if preset_id else " AND prompt=?")
            + " AND state='failed' ORDER BY created_at DESC LIMIT 1",
            [row["user"], row["video_id"], preset_id or prompt],
        )
        if failed:
            fallback.update(state="failed", request_id=failed["id"])
        return fallback

    def _set_progress(self, request_id: str, value: float) -> None:
        self.db.execute(
            "UPDATE cut_requests SET progress=?, updated_at=? WHERE id=?",
            [float(value), time.time(), request_id],
        )

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

    def _job_progress(self, job_id: str) -> float | None:
        row = self.db.one("SELECT progress FROM jobs WHERE id=?", [job_id])
        return round(float(row["progress"]), 3) if row and row["progress"] is not None else None

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
        self, user: str, video_id: str, channel_id: str | None = None
    ) -> dict[str, Any]:
        """Every preset with its state for this video and each mode; what the pickers show.

        The default follows request > channel > owner > server; `mode_rule` says which one
        chose. `channel_mode` is the owner's stored default for the video's channel, or null.
        """
        channel_id, channel_name = self._video_channel(video_id, channel_id)
        default, mode_rule = self.resolve_mode_rule(user, None, channel_id)
        from .watch import watched_available

        ok, reason = watched_available(self.cfg)
        minutes = self._meta(video_id).get("duration_s")
        eta = None
        if ok and minutes:
            watched = self.cfg.cuts.watched
            eta = int(
                round(
                    watched.eta_s_per_grid * watched.eta_grids_per_minute * float(minutes) / 60
                    + watched.eta_grid_stage_s_per_minute * float(minutes) / 60
                    + watched.eta_fixed_s
                )
            )
        modes = [
            {"id": "quick", "label": "Quick", "default": default == "quick", "available": True},
            {
                "id": "watched",
                "label": "Watched"
                + (f" · about {max(1, round((eta or 0) / 60))} min" if eta else ""),
                "default": default == "watched",
                "available": ok,
                "reason": reason,
                "eta_s": eta,
            },
        ]
        out = []
        for prompt in self.presets(user):
            quick = self._preset_state(user, video_id, prompt, "quick")
            watched = self._preset_state(user, video_id, prompt, "watched")
            top = quick if default == "quick" else watched
            entry: dict[str, Any] = {
                "id": prompt.id,
                "label": prompt.label,
                **top,
                "by_mode": {"quick": quick, "watched": watched},
            }
            out.append(entry)
        by_id = {entry["id"]: entry for entry in out}
        state = {
            "configured": self.configured,
            "default_mode": default,
            "mode_rule": mode_rule,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "channel_mode": self._channel_mode_value(user, channel_id),
            "modes": modes,
            "presets": out,
            "selection": self._selection(user, video_id, by_id),
        }
        # The validator covers everything the menu shows (selection, modes and channel mode too), not only the presets
        state["etag"] = list_etag([state])
        return state

    def _selection(
        self, user: str, video_id: str, presets: dict[str, dict[str, Any]]
    ) -> dict[str, Any] | None:
        """What the video opens with: the viewer's choice for it, else the preset used last.

        A choice that is not ready yet is still the choice: only its own request is followed, and
        no other ready preset is applied in its place. Without a choice the last-used preset is
        used only when it is ready; otherwise nothing is selected and the ready cuts are offered.
        """
        choice = self._choice(user, video_id)

        if choice is not None:
            if choice["off"]:
                return {"source": "off", "off": True, "state": "none"}

            if choice["request_id"]:
                request = self.get(choice["request_id"], user)
                if request is not None:
                    return {
                        "source": "chosen",
                        "off": False,
                        "preset_id": request.get("preset_id"),
                        "request_id": request["id"],
                        "state": request["state"],
                        **({"cut": request["cut"]} if request.get("cut") else {}),
                    }

            preset_id = choice["preset_id"]
            entry = presets.get(preset_id) if preset_id else None
            if entry is not None:
                return {
                    "source": "chosen",
                    "off": False,
                    "preset_id": preset_id,
                    "request_id": entry.get("request_id"),
                    "state": entry["state"],
                    **({"cut": entry["cut"]} if entry.get("cut") else {}),
                }

            return {"source": "chosen", "off": False, "preset_id": preset_id, "state": "none"}

        last = self._last_preset(user)
        entry = presets.get(last) if last else None
        if entry is not None and entry["state"] == "ready":
            return {
                "source": "last",
                "off": False,
                "preset_id": last,
                "request_id": entry.get("request_id"),
                "state": "ready",
                "cut": entry["cut"],
            }

        return None

    def _preset_state(self, user: str, video_id: str, prompt: Prompt, mode: str) -> dict[str, Any]:
        if mode == "watched":
            from .watch import watched_available

            ok, reason = watched_available(self.cfg)
            if not ok:
                return {"state": "unavailable", "reason": reason}
        row = self.db.one(
            "SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id=? AND mode=?"
            " AND state IN ('waiting','building','needs_transcript')"
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
            " AND preset_id=? AND mode=? AND state='failed'"
            " ORDER BY created_at DESC LIMIT 1",
            [user, video_id, prompt.id, mode],
        )
        if failed:
            return {"state": "failed", "request_id": failed["id"], "error": failed["error"]}
        return {"state": "none"}

    def _ready_cut(
        self, video_id: str, prompt: Prompt | str | None, mode: str = "quick"
    ) -> dict[str, Any] | None:
        """The stored cut for this preset, unless the transcript or the `[llm.cuts]` model
        changed since it was built."""
        model = self.cfg.llm.cuts.model if self.cfg.llm.cuts else ""
        if isinstance(prompt, Prompt):
            saved = prompt
            preset_id, instruction = prompt.id, prompt.template
        elif isinstance(prompt, str):
            saved = None
            preset_id, instruction = None, prompt
        else:
            return None
        duration = self._meta(video_id).get("duration_s")
        target_s = self.target_for(
            preset_id, float(duration) if duration else None, instruction, saved
        )
        row = self.db.one(
            "SELECT json, transcript_hash FROM cuts WHERE video_id=? AND version=? AND model=?"
            " AND mode=? ORDER BY created_at DESC LIMIT 1",
            [video_id, self._version(preset_id, instruction, target_s), model, mode],
        )
        if row is None:
            return None
        transcript = self.transcripts.cached(video_id)
        if transcript is not None and transcript.segments:
            if transcript_hash(transcript.segments) != row["transcript_hash"]:
                return None
        return json.loads(row["json"])

    # ---- repair of old near-full long cuts ------------------------------------------------------

    def repair_near_full(
        self, *, dry_run: bool = False, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Rebuild the cuts this bug left nearly uncut: a map/reduce build older than
        `CUT_BUILD_VERSION`, without a target length, that kept over `repair_near_full_frac`.

        Idempotent: the old cut row and its requests are superseded, then the same user, video and
        preset (or typed prompt) are queued again; a rebuilt cut carries the current build version,
        so it is never selected again. `dry_run` only reports."""
        if not self.configured:
            return []
        rows = self.db.all(
            "SELECT * FROM cuts WHERE COALESCE(algo_version,0) < ? ORDER BY created_at",
            [CUT_BUILD_VERSION],
        )
        items = []
        for row in rows:
            if limit is not None and len(items) >= limit:
                break
            item = self._repair_item(dict(row))
            if item is not None:
                items.append(item)
        if dry_run:
            return items
        for item in items:
            self._apply_repair(item)
        return items

    def _repair_item(self, cut: dict[str, Any]) -> dict[str, Any] | None:
        """The repair record for one stored cut, or None when it is not this bug's work."""
        duration = float(cut["duration_s"] or 0.0)
        if not duration:
            try:
                duration = float(json.loads(cut["json"] or "{}").get("duration_ms") or 0) / 1000.0
            except (TypeError, ValueError, json.JSONDecodeError):
                duration = 0.0
        kept_s = float(cut["kept_s"] or 0.0)
        if not duration or kept_s / duration <= self.cfg.cuts.repair_near_full_frac:
            return None
        requests = self.db.all(
            "SELECT id,user,source,preset_id,prompt FROM cut_requests WHERE cut_key=?"
            " ORDER BY created_at",
            [cut["cache_key"]],
        )
        wanted: list[dict[str, Any]] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for row in requests:
            found = dict(row)
            key = (found["user"], found["preset_id"], found["prompt"])
            if key in seen:
                continue
            seen.add(key)
            try:
                instruction, preset_id, _source = self._instruction(found)
            except CutRefused:
                continue
            saved = next((p for p in self.presets(found["user"]) if p.id == preset_id), None)
            target_s = self.target_for(preset_id, duration, instruction, saved)
            if target_s is not None:
                continue
            if not self._was_map_reduce(cut, instruction, target_s, duration):
                continue
            wanted.append(
                {
                    "user": found["user"],
                    "source": found["source"],
                    "preset_id": found["preset_id"],
                    "prompt": found["prompt"],
                }
            )
        if not requests:
            wanted = []
        if not wanted and requests:
            return None
        return {
            "cache_key": cut["cache_key"],
            "video_id": cut["video_id"],
            "preset_id": cut["preset_id"],
            "prompt": cut["prompt"],
            "duration_s": duration,
            "kept_s": kept_s,
            "old_share": kept_s / duration,
            "requests": wanted,
            "new": [],
        }

    def _was_map_reduce(
        self, cut: dict[str, Any], instruction: str, target_s: int | None, duration: float
    ) -> bool:
        """Whether this cut was built by map/reduce; without a stored transcript, by length."""
        transcript = self.transcripts.cached(cut["video_id"])
        if transcript is None or not transcript.segments:
            return duration >= self.cfg.cuts.repair_min_duration_s
        units = build_units(transcript.segments, self.cfg.cuts)
        if not units:
            return False
        meta = {**transcript.meta, **self._meta(cut["video_id"])}
        meta.setdefault("duration_s", duration)
        chapters = parse_chapters(meta.get("description"))
        return not self.engine.fits(units, chapters, meta, instruction, target_s)

    def _apply_repair(self, item: dict[str, Any]) -> None:
        now = time.time()
        old = self.db.all(
            "SELECT id,job_id FROM cut_requests WHERE cut_key=? AND state!='dismissed'",
            [item["cache_key"]],
        )
        for row in old:
            self.db.execute(
                "UPDATE cut_requests SET state='dismissed', error=?, updated_at=?, finished_at=?"
                " WHERE id=?",
                [REPAIR_MESSAGE, now, now, row["id"]],
            )
            if row["job_id"]:
                self.db.execute(
                    "UPDATE jobs SET status='cancelled', error=?, updated_at=?, finished_at=?"
                    " WHERE id=?",
                    [REPAIR_MESSAGE, now, now, row["job_id"]],
                )
                self.jobs.events.record(
                    row["job_id"],
                    events.FINISHED,
                    events.CANCELLED,
                    {"message": REPAIR_MESSAGE},
                )
        self.db.execute("DELETE FROM cuts WHERE cache_key=?", [item["cache_key"]])
        for spec in item["requests"]:
            request_id = self._enqueue(
                spec["user"],
                item["video_id"],
                source=spec["source"],
                preset=spec["preset_id"],
                prompt=spec["prompt"],
                klass=self.jobs._class_for(spec["user"], None),
                message=f"Rebuilt by the cut repair: the old cut kept {item['old_share']:.0%}.",
            )
            item["new"].append(
                {
                    "user": spec["user"],
                    "preset_id": spec["preset_id"],
                    "prompt": spec["prompt"],
                    "request_id": request_id,
                }
            )
        log.info(
            "cut repair: %s %s kept %.1f%% of %.0f s; %d request(s) queued",
            item["video_id"],
            item["preset_id"] or (item["prompt"] or "")[:40],
            item["old_share"] * 100,
            item["duration_s"],
            len(item["new"]),
        )

    # ---- the build ------------------------------------------------------------------------------

    def start(self) -> None:
        """Resume the builds a restart interrupted (idempotent: the cache absorbs the repeats)."""
        if self.cfg.cuts.repair_on_start:
            try:
                repaired = self.repair_near_full()
                if repaired:
                    log.info("cut repair: %d near-full cut(s) queued again", len(repaired))
            except Exception:
                log.warning("cut repair failed", exc_info=True)
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

    async def _acquire_watched(self, request_id: str, trace: events.JobTrace) -> bool:
        """One watched build at a time server-wide; others wait and say `in_line`."""
        limit = max(1, self.cfg.cuts.watched.max_concurrent)
        if self._dismissed(request_id):
            return False
        if self._watched_running < limit:
            self._watched_running += 1
            self._watched_held[request_id] = True
            return True
        trace.emit(
            events.IN_LINE,
            events.OK,
            message="A watched cut is already being built; this request waits its turn.",
        )
        while self._watched_running >= limit:
            await asyncio.sleep(self.cfg.cuts.poll_s)
            if self._dismissed(request_id):
                return False
        self._watched_running += 1
        self._watched_held[request_id] = True
        return True

    async def _acquire_user(
        self, request_id: str, user: str, trace: events.JobTrace, klass: str = NORMAL
    ) -> bool:
        """At most `max_active_per_user` builds per user run at once; the rest wait in line."""
        class_cap = self.cfg.classes.for_class(klass).max_active_cuts
        limit = max(1, min(self.cfg.cuts.max_active_per_user, class_cap))
        if self._user_running.get(user, 0) >= limit:
            trace.emit(
                events.IN_LINE,
                events.OK,
                message="Your other cuts are being built; this one starts when one finishes.",
            )
        while self._user_running.get(user, 0) >= limit:
            await asyncio.sleep(self.cfg.cuts.poll_s)
            if self._dismissed(request_id):
                return False
        self._user_running[user] = self._user_running.get(user, 0) + 1
        return True

    def _release_user(self, user: str) -> None:
        self._user_running[user] = max(0, self._user_running.get(user, 0) - 1)

    def _release_watched(self, request_id: str) -> None:
        """Give back the watched-build slot this request currently holds, if any."""
        if not self._watched_held.pop(request_id, False):
            return
        self._watched_running = max(0, self._watched_running - 1)

    async def _build(self, request_id: str) -> None:
        row = self._row(request_id)
        if row is None or row["state"] not in ("building", "needs_transcript"):
            return
        user = row["user"]
        if not await self._acquire_user(
            request_id,
            user,
            events.JobTrace(row["job_id"], self.jobs.events),
            normalize_class(row.get("klass")),
        ):
            return
        try:
            await self._build_slot(request_id, row)
        finally:
            self._release_user(user)

    async def _build_slot(self, request_id: str, row: dict[str, Any]) -> None:
        watched_slot = False
        if (row["mode"] or "quick") == "watched":
            trace = events.JobTrace(row["job_id"], self.jobs.events)
            # Wait before taking the one slot: a normal build holding it would block the prime
            # build it is waiting for.
            await self._wait_for_prime(row, trace, row.get("klass") or NORMAL)
            watched_slot = await self._acquire_watched(request_id, trace)
            if not watched_slot:
                return
        self.db.execute(
            "UPDATE jobs SET status='running', updated_at=? WHERE id=? AND status='queued'",
            [time.time(), row["job_id"]],
        )
        trace = events.JobTrace(row["job_id"], self.jobs.events)
        token = events.bind(trace)
        class_token = bind_class(row.get("klass"))
        with feature_run() as run:
            try:
                trace.emit(
                    events.STARTED,
                    events.OK,
                    kind="cuts",
                    video_id=row["video_id"],
                    **{"class": normalize_class(row.get("klass"))},
                )
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
                unbind_class(class_token)
                events.unbind(token)
                self._release_watched(request_id)
        # The build finished or was refused; remember its cost and time for the cut document.
        self._run_cost[request_id] = (run.get("cost", 0.0), run.get("elapsed_s") or 0.0)

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
        if (row["mode"] or "quick") == "watched":
            from .watch.service import WatchedBuilder

            builder = WatchedBuilder(
                self.cfg,
                self.db,
                self.llm,
                self.transcripts,
                self.prompts,
                self.jobs,
                self.archive,
                self.gate,
            )

            # A watched build yields at the next grid while a prime demanding job waits; the
            # yield drives the describing loop, so the build stops after the grid it is on. It
            # gives up the single watched slot while waiting so the prime build it yields to can
            # take it, then takes the slot back and continues at the next grid.
            async def yield_check() -> None:
                await self._wait_for_prime(
                    row, trace, row.get("klass"), release_slot_request_id=request_id
                )

            doc, cache_key = await builder.build(
                self, request_id, row, trace, yield_check=yield_check
            )
            if not self._dismissed(request_id):
                self._finish(request_id, row, cache_key, doc)
            return
        instruction, preset_id, source = self._instruction(row)
        with events.stage(STAGE_TRANSCRIPT, video_id=video_id):
            transcript = await self._ensure_transcript(request_id, row)
            # Only YouTube's automatic caption windows roll and repeat their tail; an authored
            # caption or ASR text may genuinely say the same words again, so it keeps them.
            rolling = transcript.source != SOURCE_ASR and transcript.caption_kind != CAPTION_MANUAL
            units = build_units(transcript.segments or [], self.cfg.cuts, rolling=rolling)
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
        cache_key = self._cache_key(video_id, version, model, thash)
        hit = self.db.one("SELECT json FROM cuts WHERE cache_key=?", [cache_key])
        if hit is not None:
            events.emit(STAGE_MODEL, events.SKIPPED, reason="cached")
            self._finish(request_id, row, cache_key, json.loads(hit["json"]))
            return
        while True:
            leader = self._inflight.get(cache_key)
            if leader is None:
                break
            self._build_class[cache_key] = highest(
                self._build_class.get(cache_key, NORMAL), row.get("klass")
            )
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
        self._build_class[cache_key] = highest(
            self._build_class.get(cache_key, NORMAL), row.get("klass")
        )

        def build_class() -> str:
            return self._build_class.get(cache_key, normalize_class(row.get("klass")))

        try:
            await self._wait_for_prime(row, trace, build_class)
            data, parts = await self.engine.pick_parts(
                units,
                chapters,
                meta,
                instruction,
                target_s,
                klass=build_class,
            )
            with events.stage(STAGE_CHECKING):
                guard, guard_max = keep_guards(self.cfg.cuts, preset_id, target_s)
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
                    source=source,
                    preset_id=preset_id,
                    target_s=target_s,
                )
                events.emit(
                    STAGE_CHECKING,
                    events.OK,
                    parts=len(parts),
                    kept_s=doc["kept_ms"] / 1000.0,
                    duration_s=duration_s,
                    target_s=target_s,
                )
            src = source_ref(row)
            source_obj = source_document(src)
            if source_obj is not None:
                doc["source"] = source_obj
            self.db.execute(
                "INSERT OR REPLACE INTO cuts(cache_key,video_id,version,preset_id,prompt,model,"
                "transcript_hash,json,duration_s,kept_s,created_at,mode,source_kind,source_key,"
                "release_key,release_duration_ms,algo_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                    "quick",
                    src["kind"],
                    src["key"],
                    src["release_key"],
                    src["release_duration_ms"],
                    CUT_BUILD_VERSION,
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
            self._build_class.pop(cache_key, None)
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
        # A ready cut is an inbox result: the viewer can come back and start playing it.
        if self.inbox is not None:
            meta = self._meta(row["video_id"]) or {}
            self.inbox.add(
                row["user"],
                row["video_id"],
                KIND_CUT,
                request_id,
                title=meta.get("title"),
                length_s=int(round(doc.get("duration_ms", 0) / 1000.0)) or None,
                label=doc.get("label"),
                thumbnail=thumbnail_for(meta, row["video_id"]),
            )
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

    def _version(self, preset_id: str | None, instruction: str, target_s: int | None = None) -> str:
        mark = "cut" if preset_id else "prompt"
        text = instruction
        if target_s is not None:
            cfg = self.cfg.cuts
            text += (
                f"|target={target_s}|tolerance={cfg.length_tolerance!r}"
                f"|over_ask={cfg.over_ask_frac!r}"
            )
        return f"{mark}:" + hashlib.sha256(text.encode()).hexdigest()[:16]

    @staticmethod
    def _cache_key(video_id: str, version: str, model: str, thash: str) -> str:
        return hashlib.sha256(f"{video_id}|{version}|{model}|{thash}".encode()).hexdigest()

    async def _ensure_transcript(self, request_id: str, row: dict[str, Any]) -> Transcript:
        """A timed transcript for the cut: the cached one, else a queued refresh we wait for.

        A captions row without timings (an older fetch) is dropped so the queued transcript job
        really refetches them; an ASR row without timings is refused (speech recognition is not
        free to repeat). The dropped row is shared with summaries: if the refresh then fails,
        summaries lose that cached text too and must refetch it themselves — accepted, because
        a transcript without timings is useless for cuts."""
        video_id = row["video_id"]
        forced = bool(row.get("refetch"))
        cached = self.transcripts.cached(video_id)
        if cached is not None and cached.segments and not forced:
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
            row["user"],
            video_id,
            self._meta(video_id).get("title"),
            priority=INTERACTIVE,
            force=forced,
            klass=row.get("klass"),
        )
        self.jobs.promote_transcript(video_id, row.get("klass"))
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
                # A download refused by YouTube (HTTP 403) is not a block: while the TV plays the
                # video it can upload its own captions, so wait for those instead of failing.
                if job_row["status"] == "failed" and self.transcripts.forbidden_refusal(video_id):
                    return await self._wait_for_client_captions(request_id, row, job)
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

    async def _wait_for_client_captions(
        self, request_id: str, row: dict[str, Any], job: dict[str, Any]
    ) -> Transcript:
        """A YouTube download was refused (HTTP 403): wait for the TV's own captions before failing.

        The TV uploads them through the client proxy path only while it plays the video, so this is
        a bounded wait. On success the cut builds from them; on timeout the cut fails as usual. The
        request stays `needs_transcript` with a message, so the TV shows what happens next.
        """
        video_id = row["video_id"]
        self._set_state(request_id, "needs_transcript", error=FORBIDDEN_CAPTIONS_MESSAGE)
        self.jobs.events.record(
            job["id"],
            STAGE_TRANSCRIPT,
            events.WARN,
            {"message": FORBIDDEN_CAPTIONS_MESSAGE},
        )
        usage = getattr(self.llm, "usage", None)
        if usage is not None:
            usage.add(METRIC_YOUTUBE_FORBIDDEN)
        deadline = time.monotonic() + self.cfg.cuts.client_captions_wait_s
        while time.monotonic() < deadline:
            if self._dismissed(request_id):
                raise CutRefused("The cut request was dismissed.")
            await asyncio.sleep(self.cfg.cuts.poll_s)
            cached = self.transcripts.cached(video_id)
            if cached is not None and cached.segments:
                self._set_state(request_id, "building", error=None)
                return cached
        raise CutRefused(
            f"YouTube refused the server and the TV sent no captions within "
            f"{int(self.cfg.cuts.client_captions_wait_s)} s."
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
        *,
        klass: ClassSource = NORMAL,
    ) -> tuple[Any, list[Part]]:
        """The model's final answer and the parts to keep (before padding and the checks)."""
        if self.fits(units, chapters, meta, instruction, target_s):
            task = self.task()
            with events.stage(
                STAGE_MODEL, model=task.model if task else "", units=len(units)
            ) as model_stage:
                data, parts = await self._ask_parts(
                    units, chapters, meta, instruction, target_s, klass=klass
                )
                model_stage.set(answer=json.dumps(data, ensure_ascii=False))
            return data, parts
        return await self._map_reduce(
            units,
            chapters,
            meta,
            instruction,
            target_s,
            klass=klass,
        )

    async def _ask_parts(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        *,
        cap_s: int | None = None,
        candidates: list[Candidate] | None = None,
        klass: ClassSource = NORMAL,
    ) -> tuple[Any, list[Part]]:
        """The model's answer as parts: one repair round for a broken answer and, with a target
        length, one retry that names the measured length when the answer is below the band.

        With `candidates` this is the reduce call: the model sees the candidates instead of the
        units and its answer is expanded back to parts over the real units. Without a target a
        `cap_s` maximum is applied by dropping the lowest-ranked parts, never by adding any."""
        cfg = self.cfg
        problem: str | None = None
        shown = units
        style: dict[str, Any] = {}
        if candidates is not None:
            shown = candidate_units(candidates, units, cfg.reduce_excerpt_chars)
            style = {"system": REDUCE_SYSTEM, "note": REDUCE_NOTE, "mark": CANDIDATES_MARK}
        budget_s = target_s or cap_s
        duration_s = meta.get("duration_s")
        choose_asked = below_asked = False
        while True:
            data, parts = await self._ask_parsed(
                shown,
                chapters,
                meta,
                instruction,
                target_s,
                cap_s=cap_s,
                problem=problem,
                klass=klass,
                **style,
            )
            if candidates is not None:
                parts = expand_candidate_parts(parts, candidates, units)
            if budget_s and not choose_asked:
                problem = choose_problem(parts, cfg, budget_s, duration_s)
                if problem:
                    choose_asked = True
                    events.emit(STAGE_MODEL, events.WARN, problem="ranked everything", retry=1)
                    continue
            if not target_s:
                if cap_s:
                    parts = trim_to_cap(parts, units, cfg, cap_s)
                return data, parts
            chosen, total_s = select_for_target(parts, units, cfg, target_s, duration_s)
            low, high = target_band(target_s, cfg.length_tolerance)
            if total_s >= low:
                return data, chosen
            if below_asked:
                break
            below_asked = True
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
        cap_s: int | None = None,
        problem: str | None = None,
        allow_empty: bool = False,
        klass: ClassSource = NORMAL,
        **style: Any,
    ) -> tuple[Any, list[Part]]:
        """One question and its parsed answer; a broken answer gets one repair round."""
        data = await self._ask(
            shown,
            chapters,
            meta,
            instruction,
            target_s,
            cap_s=cap_s,
            problem=problem,
            klass=klass,
            **style,
        )
        try:
            return data, parse_cut_answer(data, shown, allow_empty=allow_empty)
        except CutFormatError as exc:
            events.emit(STAGE_MODEL, events.WARN, problem=exc.problem, repair=1)
            data = await self._ask(
                shown,
                chapters,
                meta,
                instruction,
                target_s,
                cap_s=cap_s,
                problem=exc.problem,
                klass=klass,
                **style,
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
        *,
        klass: ClassSource = NORMAL,
    ) -> tuple[Any, list[Part]]:
        """A cut for a transcript too long for one request.

        Map: excerpts (on chapter boundaries when there are chapters, a few units shared with
        the previous one) are each asked to apply the task to their own text, with the excerpt's
        share of the target length or of the no-target maximum. Reduce: one call over the
        candidates picks the cut, with the same rank selection as a one-pass cut; candidates that
        do not fit one call are narrowed in rounds first. The map runs the excerpts together; a
        watched build yields between grids instead, in the describing stage."""
        cfg = self.cfg
        cap_s = self._cap_s(meta, target_s)
        chunks = self._plan_chunks(units, chapters, meta, instruction, target_s, cap_s)
        total_s = sum(u.end - u.start for u in units) or 1.0
        gate = asyncio.Semaphore(cfg.map_parallel)
        proposed: list[list[Part]] = [[] for _ in chunks]
        done = 0

        async def one(chunk: Chunk) -> None:
            nonlocal done
            core_s = sum(u.end - u.start for u in chunk.core)
            share = (
                max(1, round((target_s if target_s is not None else cap_s) * core_s / total_s))
                if target_s is not None or cap_s
                else None
            )
            share_target = share if target_s else None
            share_cap = share if target_s is None else None
            async with gate:
                parts = await self._map_chunk(
                    chunk,
                    len(chunks),
                    chapters,
                    meta,
                    instruction,
                    share_target,
                    share_cap,
                    units,
                    klass=klass,
                )
            proposed[chunk.index] = parts
            done += 1
            core_start = chunk.core[0].start
            core_end = chunk.core[-1].end
            kept_s = self._kept_seconds(parts, core_start, core_end)
            removed_s = max(0.0, core_s - kept_s)
            events.emit(
                STAGE_MAP,
                events.OK,
                excerpt=chunk.index + 1,
                of=len(chunks),
                parts=len(parts),
                kept_s=round(kept_s, 1),
                removed_s=round(removed_s, 1),
            )
            log.info(
                "cut map excerpt %d/%d: %.1f s kept, %.1f s removed (%d parts)",
                chunk.index + 1,
                len(chunks),
                kept_s,
                removed_s,
                len(parts),
            )
            events.emit(STAGE_MAP, events.RUNNING, done=done, of=len(chunks))

        with events.stage(STAGE_MAP, chunks=len(chunks), units=len(units)) as map_stage:
            events.emit(STAGE_MAP, events.RUNNING, done=0, of=len(chunks))
            await self._all([one(chunk) for chunk in chunks])
            cands = merge_candidates([c for parts in proposed for c in candidates_from(parts)])
            map_stage.set(candidates=len(cands))
        if not cands:
            raise CutRefused("Nothing was worth keeping, so there is no cut.")
        return await self._reduce(
            cands, units, chapters, meta, instruction, target_s, cap_s=cap_s, klass=klass
        )

    def _cap_s(self, meta: dict[str, Any], target_s: int | None) -> int | None:
        """The no-target maximum kept length of a map/reduce build, from the video's duration."""
        if target_s is not None:
            return None
        duration = meta.get("duration_s")
        if not duration:
            return None
        return max(MIN_TARGET_S, int(float(duration) * self.cfg.map_max_keep_frac))

    @staticmethod
    def _kept_seconds(parts: list[Part], start: float, end: float) -> float:
        """How much of `[start, end]` the parts cover, without counting their overlap twice."""
        total = 0.0
        for part in parts:
            low = max(part.start_ms / 1000.0, start)
            high = min(part.end_ms / 1000.0, end)
            if high > low:
                total += high - low
        return total

    def _plan_chunks(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        target_s: int | None,
        cap_s: int | None,
    ) -> list[Chunk]:
        cfg = self.cfg
        header = serialize_units(
            [],
            chapters,
            meta,
            instruction,
            target_s,
            cfg.over_ask_frac,
            cap_s=cap_s,
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
        share_target: int | None,
        share_cap: int | None,
        units: list[Unit],
        *,
        klass: ClassSource = NORMAL,
    ) -> list[Part]:
        """Candidate parts of one excerpt; a failed excerpt is asked once more, then the cut fails."""
        note = MAP_NOTE.format(i=chunk.index + 1, n=n)
        span = chapters_between(chapters, chunk.units[0].start, chunk.units[-1].end)
        problem = ""
        share_s = share_target or share_cap
        duration_s = meta.get("duration_s")
        for attempt in range(MAP_RETRIES + 1):
            try:
                choose: str | None = None
                for _ in range(2):
                    _data, parts = await self._ask_parsed(
                        chunk.units,
                        span,
                        meta,
                        instruction,
                        share_target,
                        cap_s=share_cap,
                        allow_empty=True,
                        note=note,
                        scope="from this excerpt",
                        problem=choose,
                        klass=klass,
                    )
                    choose = (
                        choose_problem(parts, self.cfg, share_s, duration_s) if share_s else None
                    )
                    if choose is None:
                        break
                    events.emit(
                        STAGE_MAP, events.WARN, excerpt=chunk.index + 1, problem="ranked everything"
                    )
                if share_cap:
                    parts = trim_to_cap(parts, units, self.cfg, share_cap)
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
        *,
        cap_s: int | None = None,
        klass: ClassSource = NORMAL,
    ) -> tuple[Any, list[Part]]:
        """The final choice over the candidates; too many for one call are narrowed in rounds."""
        cfg = self.cfg
        rounds = 0
        while True:
            shown = candidate_units(cands, units, cfg.reduce_excerpt_chars)
            message = serialize_units(
                shown, chapters, meta, instruction, target_s, cfg.over_ask_frac,
                cap_s=cap_s, note=REDUCE_NOTE, mark=CANDIDATES_MARK,
            )  # fmt: skip
            if self._tokens(message) <= cfg.max_input_tokens:
                with events.stage(
                    STAGE_REDUCE, candidates=len(cands), rounds=rounds
                ) as reduce_stage:
                    data, parts = await self._ask_parts(
                        units,
                        chapters,
                        meta,
                        instruction,
                        target_s,
                        cap_s=cap_s,
                        candidates=cands,
                        klass=klass,
                    )
                    kept_s = sum(_padded_s(p, cfg) for p in parts)
                    reduce_stage.set(
                        parts=len(parts),
                        kept_s=round(kept_s, 1),
                        target_s=target_s,
                        cap_s=cap_s,
                    )
                    log.info(
                        "cut reduce: %d candidates -> %d parts, %.1f s kept%s",
                        len(cands),
                        len(parts),
                        kept_s,
                        f" (target {target_s} s)"
                        if target_s
                        else (f" (cap {cap_s} s)" if cap_s else ""),
                    )
                    return data, parts
            if rounds >= cfg.max_reduce_rounds:
                raise CutRefused(
                    "This video gave too many candidate parts to choose from, so no cut was built."
                )
            rounds += 1
            narrowed = await self._reduce_round(
                cands,
                units,
                chapters,
                meta,
                instruction,
                target_s,
                cap_s,
                rounds,
                klass=klass,
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
        cap_s: int | None,
        round_no: int,
        *,
        klass: ClassSource = NORMAL,
    ) -> list[Candidate]:
        """One narrowing round: groups of candidates that fit a call each keep their best parts
        (with a target: the group's share of it, plus the usual over-ask; with a cap: at most
        the group's share of it)."""
        cfg = self.cfg
        header = serialize_units(
            [], chapters, meta, instruction, target_s, cfg.over_ask_frac,
            cap_s=cap_s, note=REDUCE_NOTE, mark=CANDIDATES_MARK,
        )  # fmt: skip
        budget = cfg.max_input_tokens * cfg.chars_per_token - len(header) - len(REDUCE_SYSTEM)
        groups = split_candidates(cands, units, budget, cfg.reduce_excerpt_chars)
        spans = [sum(units[c.last - 1].end - units[c.first - 1].start for c in g) for g in groups]
        gate = asyncio.Semaphore(cfg.map_parallel)

        async def one(group: list[Candidate], span_s: float) -> list[Candidate]:
            budget_s = target_s if target_s is not None else cap_s
            share = max(1, round(budget_s * span_s / (sum(spans) or 1.0))) if budget_s else None
            share_target = share if target_s else None
            share_cap = share if target_s is None else None
            shown = candidate_units(group, units, cfg.reduce_excerpt_chars)
            async with gate:
                _data, parts = await self._ask_parsed(
                    shown, chapters, meta, instruction, share_target,
                    cap_s=share_cap, allow_empty=True, system=REDUCE_SYSTEM,
                    note=REDUCE_NOTE, mark=CANDIDATES_MARK, klass=klass,
                )  # fmt: skip
            kept = expand_candidate_parts(parts, group, units)
            if share_target and kept:
                kept, _ = select_for_target(
                    kept,
                    units,
                    cfg,
                    int(share_target * (1 + cfg.over_ask_frac)),
                    meta.get("duration_s"),
                )
            elif share_cap and kept:
                kept = trim_to_cap(kept, units, cfg, share_cap, meta.get("duration_s"))
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
        cap_s: int | None = None,
        problem: str | None = None,
        system: str = CUT_SYSTEM,
        note: str | None = None,
        scope: str = "in total",
        mark: str = UNITS_MARK,
        klass: ClassSource = NORMAL,
    ) -> Any:
        """The model's parsed answer. One repair round when the ids break the rules."""
        klass = klass() if callable(klass) else klass
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
            cap_s=cap_s,
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
        return await self.llm.chat_json(
            task, messages, priority=INTERACTIVE, klass=klass, feature=task.feature
        )
