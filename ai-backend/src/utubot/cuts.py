"""Director's cuts: a model picks which parts of a video to keep, the TV skips the rest.

A cut request (preset or a prompt the owner typed) runs as its own async task: it makes sure a
timed transcript exists, merges the caption fragments into sentence-like units, asks the
`[llm.cuts]` model for the unit ranges to keep, validates and repairs the answer, and stores the
finished cut under a cache key shared by every user. The job row and its events are only the
report; the queue the phone shows is the `cut_requests` table.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .captions import events
from .captions.jobs import JobQueue
from .config import Config
from .db import Database
from .llm import INTERACTIVE, LLMClient, LLMError
from .prompts import Prompt, PromptStore
from .transcripts import SOURCE_ASR, Transcript, TranscriptService, fmt_ts

log = logging.getLogger("utubot.cuts")

# Stages this feature writes into the job report (the captions pipeline writes the others).
STAGE_TRANSCRIPT = "transcript"
STAGE_MODEL = "model"
STAGE_CHECKING = "checking"

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
PRESET_LABELS = {
    "cut-no-filler": "No filler",
    "cut-answer": "Just the answer",
    "cut-demo": "Only the demo",
    "cut-highlights-5": "Highlights in 5 min",
}

CUT_SYSTEM = (
    "You build director's cuts of YouTube videos for a TV viewer: you choose which numbered "
    "transcript units to keep so the video plays the way the task asks. Reply ONLY with JSON: "
    '{"parts":[{"from":<int>,"to":<int>,"label":"<2-6 words>"}],'
    '"summary":"<one line, at most 120 characters>","kept_s":<int>}. '
    '"from" and "to" are the first and last unit id of one kept part. Ranges never overlap, ids '
    "must exist, and parts stay in video order. Be faithful to the transcript; never invent "
    "content and never add commentary."
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


def serialize_units(
    units: list[Unit],
    chapters: list[tuple[float, str]],
    meta: dict[str, Any],
    instruction: str,
) -> str:
    """The user message the cut model answers: the video facts, the task, then the numbered units."""
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
    lines.append(UNITS_MARK)
    lines.extend(f"#{u.n} [{fmt_ts(u.start)}-{fmt_ts(u.end)}] {u.text}" for u in units)
    lines.append("Answer with the JSON object the system message describes.")
    return "\n".join(lines)


def parse_cut_answer(data: Any, units: list[Unit]) -> list[Part]:
    """The model's JSON answer as kept parts, or `CutFormatError` naming the problem."""
    if not isinstance(data, dict):
        raise CutFormatError("the answer is not a JSON object")
    raw_parts = data.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise CutFormatError("'parts' is missing or empty")
    last_to = 0
    out: list[Part] = []
    for i, raw in enumerate(raw_parts):
        if not isinstance(raw, dict):
            raise CutFormatError(f"part {i + 1} is not an object")
        try:
            start_n = int(raw["from"])
            end_n = int(raw["to"])
        except (KeyError, TypeError, ValueError):
            raise CutFormatError(f"part {i + 1} has no valid from/to unit ids") from None
        if not 1 <= start_n <= end_n <= len(units):
            raise CutFormatError(
                f"part {i + 1} names units {start_n}-{end_n}; the transcript has 1-{len(units)}"
            )
        if start_n <= last_to:
            raise CutFormatError(f"part {i + 1} overlaps or goes before part {i}")
        label = _clean_text(str(raw.get("label") or ""))[:80]
        out.append(
            Part(
                label or f"Part {i + 1}",
                int(units[start_n - 1].start * 1000),
                int(units[end_n - 1].end * 1000),
            )
        )
        last_to = end_n
    return out


def finalize_parts(
    parts: list[Part], cfg, *, guard: bool, duration_s: float | None
) -> tuple[list[Part], float | None]:
    """Pad, merge and drop the kept parts; check how much of the video survives.

    Gaps under `cuts.merge_gap_s` are merged, parts under `cuts.min_part_s` are dropped, and
    boundaries are padded `pad_before_s`/`pad_after_s`. A cut keeping under `min_keep_frac`
    ("this would remove almost everything") or over `max_keep_frac` ("nothing to cut") is
    refused, unless `guard` is off (the highlights presets accept their real length).
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
        frac = kept_ms / (duration_s * 1000)
        if frac < cfg.min_keep_frac:
            raise CutRefused("This cut would remove almost everything, so it was not applied.")
        if frac > cfg.max_keep_frac:
            raise CutRefused("Nothing to cut: this keeps nearly the whole video.")
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
) -> dict[str, Any]:
    """The wire document the phone and the TV read: kept parts, skip ranges in ms, the transcript
    hash and the length the cut was built for (the TV refuses a cut whose length differs)."""
    duration_ms = int((duration_s or 0) * 1000)
    if not duration_ms and parts:
        duration_ms = parts[-1].end_ms
    return {
        "version": CUT_DOC_VERSION,
        "video_id": video_id,
        "transcript_hash": thash,
        "duration_ms": duration_ms,
        "label": label[:80],
        "summary": (summary or "")[:300],
        "parts": [{"label": p.label, "start_ms": p.start_ms, "end_ms": p.end_ms} for p in parts],
        "skip_ranges_ms": skip_ranges_ms(parts, duration_ms),
        "kept_ms": sum(p.end_ms - p.start_ms for p in parts),
        "source": source,
        "preset_id": preset_id,
        "model": model,
        "built_at": built_at or time.time(),
    }


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
    ) -> dict[str, Any]:
        """Queue a cut. Exactly one of `preset` / `prompt`; `await_prompt` creates an empty
        request the phone fills later. An identical active request is returned as-is."""
        if not self.configured:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
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
        existing = self._active_same(user, video_id, preset, prompt, await_prompt)
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
            "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
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
        self, user: str, video_id: str, preset: str | None, prompt: str | None, await_prompt: bool
    ) -> dict[str, Any] | None:
        states = (*BUILDING_STATES, "waiting")
        marks = ",".join("?" * len(states))
        if await_prompt:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id IS NULL"
                f" AND prompt IS NULL AND state IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                [user, video_id, *states],
            )
        elif prompt is not None:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND prompt=?"
                f" AND state IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                [user, video_id, prompt, *states],
            )
        else:
            row = self.db.one(
                f"SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id=?"
                f" AND state IN ({marks}) ORDER BY created_at DESC LIMIT 1",
                [user, video_id, preset, *states],
            )
        return dict(row) if row else None

    def fill(self, request_id: str, user: str, prompt: str) -> dict[str, Any]:
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
        self._check_cap(user)
        self.db.execute(
            "UPDATE cut_requests SET prompt=?, state='building', updated_at=? WHERE id=?",
            [prompt, time.time(), request_id],
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
        if row["state"] in BUILDING_STATES and row["job_id"]:
            out["stage"] = self._last_stage(row["job_id"])
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

    def presets_state(self, user: str, video_id: str) -> dict[str, Any]:
        """Every preset with its state for this video: what the TV's picker and the phone show."""
        out = []
        for prompt in self.presets(user):
            entry: dict[str, Any] = {"id": prompt.id, "label": prompt.label}
            row = self.db.one(
                "SELECT * FROM cut_requests WHERE user=? AND video_id=? AND preset_id=?"
                " AND state IN ('waiting','building','needs_transcript')"
                " ORDER BY created_at DESC LIMIT 1",
                [user, video_id, prompt.id],
            )
            if row:
                entry.update(state=row["state"], request_id=row["id"])
            else:
                cut = self._ready_cut(video_id, prompt)
                if cut is not None:
                    entry.update(state="ready", cut=cut)
                else:
                    failed = self.db.one(
                        "SELECT id, error FROM cut_requests WHERE user=? AND video_id=?"
                        " AND preset_id=? AND state='failed' ORDER BY created_at DESC LIMIT 1",
                        [user, video_id, prompt.id],
                    )
                    if failed:
                        entry.update(state="failed", request_id=failed["id"], error=failed["error"])
                    else:
                        entry.update(state="none")
            out.append(entry)
        return {"configured": self.configured, "presets": out}

    def _ready_cut(self, video_id: str, prompt: Prompt) -> dict[str, Any] | None:
        """The stored cut for this preset, unless the transcript or the `[llm.cuts]` model
        changed since it was built."""
        model = self.cfg.llm.cuts.model if self.cfg.llm.cuts else ""
        row = self.db.one(
            "SELECT json, transcript_hash FROM cuts WHERE video_id=? AND version=? AND model=?"
            " ORDER BY created_at DESC LIMIT 1",
            [video_id, self._version(prompt.id, prompt.template), model],
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
        instruction, preset_id, source = self._instruction(row)
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
        version = self._version(preset_id, instruction)
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
            events.emit(STAGE_MODEL, events.SKIPPED, reason="shared build")
            try:
                doc = await asyncio.shield(leader)
            except asyncio.CancelledError:
                if self._dismissed(request_id) or not leader.cancelled():
                    raise
                continue  # the leader was dismissed; its cache key is free again
            self._finish(request_id, row, cache_key, doc)
            return
        leader = asyncio.get_running_loop().create_future()
        leader.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        self._inflight[cache_key] = leader
        try:
            with events.stage(STAGE_MODEL, model=model, units=len(units)) as model_stage:
                data = await self._ask(units, chapters, meta, instruction)
                try:
                    parts = parse_cut_answer(data, units)
                except CutFormatError as exc:
                    trace.emit(STAGE_MODEL, events.WARN, problem=exc.problem, repair=1)
                    data = await self._ask(units, chapters, meta, instruction, problem=exc.problem)
                    try:
                        parts = parse_cut_answer(data, units)
                    except CutFormatError as exc2:
                        raise CutRefused(
                            f"The model's answer stayed unusable ({exc2.problem}),"
                            " so no cut was built."
                        ) from exc2
                model_stage.set(answer=json.dumps(data, ensure_ascii=False))
            if self._dismissed(request_id):
                return
            with events.stage(STAGE_CHECKING):
                duration_s = meta.get("duration_s")
                duration_s = float(duration_s) if duration_s else None
                guard = not (preset_id or "").endswith("highlights-5")
                parts, _kept_s = finalize_parts(
                    parts, self.cfg.cuts, guard=guard, duration_s=duration_s
                )
                doc = cut_document(
                    video_id=video_id,
                    thash=thash,
                    model=model,
                    parts=parts,
                    summary=str(data.get("summary") or ""),
                    label=self._label(preset_id, row),
                    duration_s=duration_s,
                    source=source,
                    preset_id=preset_id,
                )
                events.emit(
                    STAGE_CHECKING,
                    events.OK,
                    parts=len(parts),
                    kept_s=doc["kept_ms"] / 1000.0,
                    duration_s=duration_s,
                )
            self.db.execute(
                "INSERT OR REPLACE INTO cuts(cache_key,video_id,version,preset_id,prompt,model,"
                "transcript_hash,json,duration_s,kept_s,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
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

    @staticmethod
    def _label(preset_id: str | None, row: dict[str, Any]) -> str:
        if row["prompt"]:
            return row["prompt"]
        return PRESET_LABELS.get(preset_id or "", preset_id or "Cut")

    @staticmethod
    def _version(preset_id: str | None, instruction: str) -> str:
        mark = "cut" if preset_id else "prompt"
        return f"{mark}:" + hashlib.sha256(instruction.encode()).hexdigest()[:16]

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

    async def _ask(
        self,
        units: list[Unit],
        chapters: list[tuple[float, str]],
        meta: dict[str, Any],
        instruction: str,
        *,
        problem: str | None = None,
    ) -> Any:
        """The model's parsed answer. One repair round when the ids break the rules."""
        task = self.cfg.llm.cuts
        if task is None:
            raise CutRefused("Cuts are not configured on this server (no [llm.cuts] model).")
        message = serialize_units(units, chapters, meta, instruction)
        if len(message) // self.cfg.cuts.chars_per_token > self.cfg.cuts.max_input_tokens:
            raise CutRefused("This video is too long to cut in one pass (no map/reduce yet).")
        messages = [
            {"role": "system", "content": CUT_SYSTEM},
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
