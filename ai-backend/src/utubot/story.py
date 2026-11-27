"""Story-aware cuts of a film (ai/FILM_CUTS_PLAN.md, checkpoint 1): pure code, no network.

The film is read once into a story map (scenes, beats, cast), the beats are linked by cause and
effect (`needs`), a model scores the beats against a purpose, and code, not the model, builds the
cut: every beat a kept beat needs is kept (closure), the length is held by adding and removing
whole beats, and a critic reads the result as a viewer would. `run_story` drives the four model
steps through caller-supplied callables, so the offline bench and the tests share one path.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .cuts import Unit, unit_line
from .prompts import (
    STORY_CRITIC_SYSTEM,
    STORY_LINK_SYSTEM,
    STORY_READ_SYSTEM,
    STORY_SELECT_SYSTEM,
)
from .transcripts import fmt_ts

BEAT_KINDS = ("setup", "payoff", "turn", "reveal", "gag", "connective")
CRITIC_TYPES = (
    "missing_cause",
    "unknown_person",
    "dangling_setup",
    "filler",
    "abrupt",
    "goal",
)
MUSIC_RE = re.compile(r"^[\s\[\(]*(m[uü]zik|music|♪+)[\s\]\)♪]*$", re.IGNORECASE)
THREAD_RANK = {"keep": 2, "compress": 1, "drop": 0}


@dataclass(frozen=True)
class StoryParams:
    """Every tunable of the story method (plan 2.2 to 2.8); checkpoint 2 moves them to config."""

    pause_mark_s: float = 3.0
    beat_max_s: float = 240.0
    read_window_tokens: int = 20000
    read_overlap_units: int = 8
    read_context_beats: int = 12
    chars_per_token: float = 2.7
    max_needs: int = 4
    length_tolerance: float = 0.10
    min_quarter_ratio: float = 0.5
    max_skip_s: float = 600.0
    max_skip_min_target_frac: float = 0.4
    default_keep: int = 1
    repair_rounds: int = 2
    accept_consistency: int = 8
    accept_density: int = 7
    accept_goal: int = 7
    merge_gap_s: float = 2.0
    skip_note_min_s: float = 120.0
    quarters: int = 4
    a6_max_dangling: int = 2
    a7_min_ratio: float = 1.10


class StoryFormatError(ValueError):
    """A model answer breaks the story rules; the text is the reason sent back for the repair."""


@dataclass
class Reply:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


ModelFn = Callable[[list[dict[str, str]]], Reply]


@dataclass
class Beat:
    id: int
    scene: int
    first: int  # first and last unit id
    last: int
    start: float
    end: float
    what: str
    where: str = ""
    who: list[str] = field(default_factory=list)
    kind: str = "connective"
    weight: int = 2
    needs: list[int] = field(default_factory=list)
    why: str = ""

    @property
    def dur(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass
class StoryMap:
    kind: str
    language: str
    synopsis: str
    cast: list[dict[str, Any]]
    beats: list[Beat]
    threads: list[dict[str, Any]] = field(default_factory=list)
    ending: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Selection:
    kept: set[int]
    over_target: bool = False


@dataclass
class CallRecord:
    step: str
    seconds: float
    prompt_tokens: int
    completion_tokens: int


# ---- step 0: lines the model reads ---------------------------------------------------------


def is_music(unit: Unit) -> bool:
    return bool(MUSIC_RE.match(unit.text))


def selectable(units: list[Unit]) -> list[Unit]:
    """The units a beat can be made of: music marks are structure, not content."""
    return [u for u in units if not is_music(u)]


def story_lines(units: list[Unit], params: StoryParams) -> list[str]:
    """Unit lines plus `--- pause N s ---` and `--- music ---` marks the model can use, not select."""
    out: list[str] = []
    prev_end: float | None = None
    for u in units:
        if prev_end is not None and u.start - prev_end >= params.pause_mark_s:
            out.append(f"--- pause {int(u.start - prev_end)} s ---")
        out.append("--- music ---" if is_music(u) else unit_line(u))
        prev_end = max(prev_end or 0.0, u.end)
    return out


def extract_json(text: str) -> Any:
    body = text.strip()
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", body)
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        raise StoryFormatError("the answer holds no JSON object")
    try:
        return json.loads(body[start : end + 1])
    except ValueError as exc:
        raise StoryFormatError(f"the answer is not valid JSON ({exc.msg})") from None


# ---- step 1: read -------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value == int(value):
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("#").isdigit():
        return int(value.strip().lstrip("#"))
    return None


def _tile(ranges: list[tuple[int | None, int | None]], ids: list[int], label: str) -> None:
    """The ranges must cover `ids` in order with no gap and no overlap."""
    pos = {uid: i for i, uid in enumerate(ids)}
    expect = 0
    for i, (a, b) in enumerate(ranges, 1):
        if a is None or b is None or a not in pos or b not in pos:
            raise StoryFormatError(f"{label} {i} has a unit id that does not exist in this input")
        if pos[a] != expect:
            want = ids[expect] if expect < len(ids) else "the end"
            raise StoryFormatError(
                f"{label} {i} starts at #{a} but must start at #{want}: no gap, no overlap"
            )
        if pos[b] < pos[a]:
            raise StoryFormatError(f"{label} {i} ends before it starts")
        expect = pos[b] + 1
    if expect != len(ids):
        raise StoryFormatError(
            f"the {label}s stop at #{ids[expect - 1]}; they must reach #{ids[-1]}"
        )


def parse_read(
    data: Any, units: list[Unit], *, snap: bool = False
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Header fields and the scenes (with beats) of one read answer over `units` (selectable ones).

    Scenes tile the units, beats tile their scene. With `snap` a gap or overlap is closed by
    moving the boundary (the last resort after the repair round)."""
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or not data["scenes"]:
        raise StoryFormatError('the answer needs a "scenes" list')
    ids = [u.n for u in units]
    scenes = data["scenes"]
    if snap:
        scenes = _snap_scenes(scenes, ids)
    _tile([(_int(s.get("from")), _int(s.get("to"))) for s in scenes], ids, "scene")
    for i, scene in enumerate(scenes, 1):
        beats = scene.get("beats")
        if not isinstance(beats, list) or not beats:
            raise StoryFormatError(f"scene {i} has no beats")
        lo, hi = _int(scene["from"]), _int(scene["to"])
        inner = [uid for uid in ids if lo <= uid <= hi]  # type: ignore[operator]
        _tile(
            [(_int(b.get("from")), _int(b.get("to"))) for b in beats], inner, f"beat of scene {i}"
        )
        if any(not str(b.get("what") or "").strip() for b in beats):
            raise StoryFormatError(f'every beat of scene {i} needs a "what"')
    header = {k: data.get(k) for k in ("kind", "language", "synopsis", "cast")}
    return header, scenes


def _snap_scenes(scenes: list[Any], ids: list[int]) -> list[Any]:
    """Close gaps and overlaps by making each scene and beat start where the previous one ended."""
    pos = {uid: i for i, uid in enumerate(ids)}

    def fix(rows: list[Any], lo: int, hi: int) -> list[Any]:
        rows = [r for r in rows if isinstance(r, dict) and _int(r.get("to")) in pos]
        rows.sort(key=lambda r: pos[_int(r["to"])])  # type: ignore[index]
        out: list[Any] = []
        nxt = lo
        for r in rows:
            end = pos[_int(r["to"])]  # type: ignore[index]
            if end < nxt:
                continue
            out.append({**r, "from": ids[nxt], "to": ids[end]})
            nxt = end + 1
        if out and nxt <= hi:
            out[-1] = {**out[-1], "to": ids[hi]}
        return out

    fixed = fix(scenes, 0, len(ids) - 1)
    for scene in fixed:
        lo, hi = pos[scene["from"]], pos[scene["to"]]
        beats = fix(scene.get("beats") or [], lo, hi)
        scene["beats"] = beats
    return [s for s in fixed if s["beats"]]


def split_long(
    beats: list[Beat], by_id: dict[int, Unit], order: list[int], params: StoryParams
) -> list[Beat]:
    """A beat over `beat_max_s` is split at its largest pause, repeatedly."""
    pos = {uid: i for i, uid in enumerate(order)}
    out: list[Beat] = []
    stack = list(reversed(beats))
    while stack:
        b = stack.pop()
        a, z = pos[b.first], pos[b.last]
        if b.dur <= params.beat_max_s or z == a:
            out.append(b)
            continue
        mid = (a + z) / 2
        cut = max(
            range(a, z),
            key=lambda i: (
                by_id[order[i + 1]].start - by_id[order[i]].end,
                -abs(i - mid),
            ),
        )
        left_u, right_u = by_id[order[cut]], by_id[order[cut + 1]]
        what = b.what if b.what.endswith("(cont.)") else b.what
        left = Beat(0, b.scene, b.first, left_u.n, b.start, left_u.end, what, b.where, b.who)
        right = Beat(
            0, b.scene, right_u.n, b.last, right_u.start, b.end, f"{what} (cont.)", b.where, b.who
        )
        stack.append(right)
        stack.append(left)
    return out


def read_windows(units: list[Unit], params: StoryParams) -> list[tuple[list[Unit], int]]:
    """Sequential windows of `read_window_tokens` with `read_overlap_units` of context before each
    but the first; the second item is the first unit id the window must cover."""
    budget = int(params.read_window_tokens * params.chars_per_token)
    out: list[tuple[list[Unit], int]] = []
    i = 0
    while i < len(units):
        size, j = 0, i
        while j < len(units) and (size < budget or j == i):
            size += len(units[j].text) + 24
            j += 1
        start = max(0, i - params.read_overlap_units) if i else 0
        out.append((units[start:j], units[i].n))
        i = j
    return out


def _meta_lines(meta: dict[str, Any], chapters: list[tuple[float, str]]) -> list[str]:
    duration = meta.get("duration_s")
    lines = [
        f"Title: {meta.get('title') or ''}",
        f"Channel: {meta.get('channel') or ''}",
        f"Duration: {fmt_ts(duration) if duration else 'unknown'}",
    ]
    if chapters:
        lines.append("Chapters:")
        lines.extend(f"- {fmt_ts(at)} {title}" for at, title in chapters)
    return lines


def card(b: Beat) -> str:
    who = ",".join(b.who)
    return (
        f"B{b.id} [{fmt_ts(b.start)}-{fmt_ts(b.end)}] scene {b.scene} ({b.where}; {who}): {b.what}"
    )


class Recorder:
    """Collects one `CallRecord` per model call."""

    def __init__(self) -> None:
        self.calls: list[CallRecord] = []
        self.last_text = ""

    def ask(
        self,
        step: str,
        fn: ModelFn,
        messages: list[dict[str, str]],
        parse: Callable[[Any, int], Any],
        rounds: int = 1,
    ) -> Any:
        """One model call, one repair round when the answer breaks the rules. `parse(data, attempt)`
        raises `StoryFormatError`; the last attempt is the repair round's answer."""
        msgs = list(messages)
        for attempt in range(rounds + 1):
            reply = fn(msgs)
            self.last_text = reply.text
            self.calls.append(
                CallRecord(step, reply.seconds, reply.prompt_tokens, reply.completion_tokens)
            )
            try:
                return parse(extract_json(reply.text), attempt)
            except StoryFormatError as exc:
                if attempt == rounds:
                    raise
                msgs = [
                    *messages,
                    {"role": "assistant", "content": reply.text},
                    {
                        "role": "user",
                        "content": f"Your answer was rejected: {exc} Reply with the full "
                        "corrected JSON object.",
                    },
                ]
        raise StoryFormatError("no answer")  # pragma: no cover


def read_film(
    units: list[Unit],
    meta: dict[str, Any],
    chapters: list[tuple[float, str]],
    fn: ModelFn,
    params: StoryParams,
    rec: Recorder,
) -> StoryMap:
    """Step 1: the film into scenes, beats and cast, in sequential windows."""
    sel = selectable(units)
    by_id = {u.n: u for u in units}
    order = [u.n for u in sel]
    beats: list[Beat] = []
    notes: list[str] = []
    header: dict[str, Any] = {}
    scene_no = 0
    for w, (window, first_id) in enumerate(read_windows(sel, params), 1):
        lines = story_lines([u for u in units if window[0].n <= u.n <= window[-1].n], params)
        user = _meta_lines(meta, chapters)
        if header:
            user.append(f"Synopsis so far: {header.get('synopsis') or ''}")
            user.append("Cast so far: " + json.dumps(header.get("cast") or [], ensure_ascii=False))
            user.append("Last beats already described:")
            user.extend(f"- {b.what}" for b in beats[-params.read_context_beats :])
            user.append(
                f"Cover the units from #{first_id} to #{window[-1].n} only; the units before "
                f"#{first_id} are context. Return the full cast (old and new) and the synopsis "
                "of the film so far."
            )
        else:
            user.append(f"Cover the units from #{first_id} to #{window[-1].n}.")
        user.append("Units:")
        user.extend(lines)
        user.append("Answer with the JSON object the system message describes.")
        cover = [u for u in window if u.n >= first_id]
        messages = [
            {"role": "system", "content": STORY_READ_SYSTEM},
            {"role": "user", "content": "\n".join(user)},
        ]
        snapped: list[bool] = []

        def parse(
            data: Any, attempt: int, cover: list[Unit] = cover, snapped: list[bool] = snapped
        ):
            try:
                return parse_read(data, cover)
            except StoryFormatError:
                if attempt < 1:
                    raise
                snapped.append(True)
                return parse_read(data, cover, snap=True)

        header_w, scenes = rec.ask("read", fn, messages, parse)
        if snapped:
            notes.append(f"read window {w}: gaps or overlaps closed by code after the repair round")
        if w == 1 or header_w.get("synopsis"):
            header = {**header, **{k: v for k, v in header_w.items() if v}}
        for scene in scenes:
            scene_no += 1
            for b in scene["beats"]:
                lo, hi = by_id[_int(b["from"])], by_id[_int(b["to"])]  # type: ignore[index]
                who = [str(x) for x in (scene.get("who") or []) if isinstance(x, str)]
                beats.append(
                    Beat(
                        0,
                        scene_no,
                        lo.n,
                        hi.n,
                        lo.start,
                        hi.end,
                        str(b["what"]).strip(),
                        str(scene.get("where") or "")[:40],
                        who,
                    )
                )
    beats = split_long(beats, by_id, order, params)
    for i, b in enumerate(beats, 1):
        b.id = i
    return StoryMap(
        kind=str(header.get("kind") or "story"),
        language=str(header.get("language") or ""),
        synopsis=str(header.get("synopsis") or ""),
        cast=[c for c in (header.get("cast") or []) if isinstance(c, dict)],
        beats=beats,
        notes=notes,
    )


# ---- step 2: link -------------------------------------------------------------------------


def parse_link(data: Any, smap: StoryMap, params: StoryParams, *, strict: bool) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("beats"), list):
        raise StoryFormatError('the answer needs a "beats" list')
    known = {b.id for b in smap.beats}
    rows: dict[int, dict[str, Any]] = {}
    for row in data["beats"]:
        bid = _int(row.get("id")) if isinstance(row, dict) else None
        if bid in known:
            rows[bid] = row  # type: ignore[index]
    soft: list[str] = []
    for bid, row in rows.items():
        needs = [n for n in (_int(x) for x in row.get("needs") or []) if n in known]
        bad = [n for n in needs if n is not None and n >= bid]
        if bad:
            soft.append(f"beat {bid} needs {bad}, which are not earlier beats")
        if row.get("kind") in ("payoff", "reveal") and not [n for n in needs if n < bid]:
            soft.append(f"beat {bid} is a {row['kind']} and needs at least one earlier beat")
    ending = [e for e in (_int(x) for x in data.get("ending") or []) if e in known]
    if not ending:
        raise StoryFormatError('"ending" must list the beats that make up the ending')
    if strict and soft:
        raise StoryFormatError("; ".join(soft[:12]) + ".")
    return {"rows": rows, "ending": ending, "threads": data.get("threads") or [], "soft": soft}


def apply_link(smap: StoryMap, parsed: dict[str, Any], params: StoryParams) -> None:
    known = {b.id for b in smap.beats}
    for b in smap.beats:
        row = parsed["rows"].get(b.id)
        if not row:
            continue
        kind = row.get("kind")
        b.kind = kind if kind in BEAT_KINDS else "connective"
        weight = _int(row.get("weight"))
        b.weight = min(5, max(1, weight if weight is not None else 2))
        needs = []
        for x in row.get("needs") or []:
            n = _int(x)
            if n in known and n is not None and n < b.id and n not in needs:
                needs.append(n)
        b.needs = needs[: params.max_needs]
        b.why = str(row.get("why") or "")[:100]
    smap.ending = parsed["ending"]
    threads = []
    for t in parsed["threads"]:
        if isinstance(t, dict) and t.get("id"):
            ids = [n for n in (_int(x) for x in t.get("beats") or []) if n in known]
            threads.append(
                {"id": str(t["id"]), "title": str(t.get("title") or "")[:60], "beats": ids}
            )
    smap.threads = threads
    if parsed["soft"]:
        smap.notes.append(f"link: {len(parsed['soft'])} soft problems left after the repair round")


def link_film(smap: StoryMap, fn: ModelFn, params: StoryParams, rec: Recorder) -> None:
    """Step 2: causes between beats, from the beat cards alone."""
    user = [
        f"Synopsis: {smap.synopsis}",
        "Cast: " + json.dumps(smap.cast, ensure_ascii=False),
        "Beats:",
        *(card(b) for b in smap.beats),
        "Answer with the JSON object the system message describes.",
    ]
    messages = [
        {"role": "system", "content": STORY_LINK_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
    parsed = rec.ask(
        "link", fn, messages, lambda d, attempt: parse_link(d, smap, params, strict=attempt < 1)
    )
    apply_link(smap, parsed, params)


# ---- step 3: closure, selection ------------------------------------------------------------


def purpose_brief(purpose: str, target_s: int, duration_s: float) -> str:
    return (
        f"Purpose: {purpose}\n"
        "Viewer: has not seen the film. Everything you keep must be understandable from what is "
        "kept before it.\n"
        f"Length: {fmt_ts(target_s)} of {fmt_ts(duration_s)}. Rules: keep causes with their "
        "results; prefer dropping a whole thread to keeping its ending alone; the ending must "
        "stay and must be earned."
    )


def closure(ids: set[int], by_id: dict[int, Beat]) -> set[int]:
    """`ids` plus every beat reachable through `needs`."""
    out = set(ids)
    stack = list(ids)
    while stack:
        for n in by_id[stack.pop()].needs:
            if n in by_id and n not in out:
                out.add(n)
                stack.append(n)
    return out


def _quarter(beat: Beat, duration_s: float, params: StoryParams) -> int:
    return min(params.quarters - 1, int(beat.start / duration_s * params.quarters))


def quarter_shares(
    kept: set[int], smap: StoryMap, duration_s: float, params: StoryParams
) -> list[float]:
    total = [0.0] * params.quarters
    got = [0.0] * params.quarters
    for b in smap.beats:
        q = _quarter(b, duration_s, params)
        total[q] += b.dur
        if b.id in kept:
            got[q] += b.dur
    return [g / t if t else 1.0 for g, t in zip(got, total, strict=True)]


def kept_seconds(kept: set[int], by_id: dict[int, Beat]) -> float:
    return sum(by_id[i].dur for i in kept)


def skips(kept: set[int], smap: StoryMap) -> list[tuple[float, float]]:
    """Gaps between consecutive kept beats (start of the film and end are not counted)."""
    rows = sorted((b for b in smap.beats if b.id in kept), key=lambda b: b.start)
    return [(a.end, b.start) for a, b in zip(rows, rows[1:], strict=False) if b.start > a.end]


def select_beats(
    smap: StoryMap,
    keep: dict[int, int],
    thread_rank: dict[int, int],
    target_s: float,
    duration_s: float,
    params: StoryParams,
    *,
    forced: set[int] | None = None,
    forbidden: set[int] | None = None,
) -> Selection:
    """Step 3, by code: must-keeps and the ending, closure, then add or remove whole beats to hold
    the length; balance across the runtime; fill skips that are too long. Closure is never broken
    by a removal: only beats no kept beat needs, outside the ending's closure, can go."""
    by_id = {b.id: b for b in smap.beats}
    forced = set(forced or ())
    forbidden = set(forbidden or ()) - set(smap.ending) - forced
    upper = target_s * (1 + params.length_tolerance)

    def score(b: Beat) -> tuple[int, int, int]:
        return (keep.get(b.id, params.default_keep), b.weight, thread_rank.get(b.id, 1))

    protected = closure(set(smap.ending) | forced, by_id)
    kept = closure(
        set(smap.ending)
        | forced
        | {i for i, k in keep.items() if k >= 3 and i in by_id and i not in forbidden},
        by_id,
    )

    def starved_quarters() -> set[int]:
        overall = kept_seconds(kept, by_id) / sum(b.dur for b in smap.beats)
        if overall <= 0:
            return set()
        shares = quarter_shares(kept, smap, duration_s, params)
        return {q for q, s in enumerate(shares) if s < params.min_quarter_ratio * overall}

    def add_one(pool: list[Beat], ceiling: float) -> bool:
        for b in pool:
            add = closure({b.id}, by_id) - kept
            if add and kept_seconds(kept, by_id) + kept_seconds(add, by_id) <= ceiling:
                kept.update(add)
                return True
        return False

    while kept_seconds(kept, by_id) < target_s:
        pool = [b for b in smap.beats if b.id not in kept and b.id not in forbidden]
        pool.sort(key=lambda b: (tuple(-x for x in score(b)), b.id))
        starved = starved_quarters()
        first = [b for b in pool if _quarter(b, duration_s, params) in starved]
        if not (first and add_one(first, upper)) and not add_one(pool, upper):
            break

    over = False

    def remove_one(exclude: set[int]) -> bool:
        needed = {n for i in kept for n in by_id[i].needs}
        starved = starved_quarters()
        pool = [
            by_id[i] for i in kept if i not in needed and i not in protected and i not in exclude
        ]
        if not pool:
            return False
        pool.sort(key=lambda b: (_quarter(b, duration_s, params) in starved, score(b), b.start))
        kept.discard(pool[0].id)
        return True

    while kept_seconds(kept, by_id) > upper:
        if not remove_one(set()):
            over = True
            break

    if params.max_skip_s and target_s / duration_s >= params.max_skip_min_target_frac:
        for _ in range(len(smap.beats)):
            long_gaps = [g for g in skips(kept, smap) if g[1] - g[0] > params.max_skip_s]
            if not long_gaps:
                break
            lo, hi = max(long_gaps, key=lambda g: g[1] - g[0])
            span = hi - lo
            mid = [
                b
                for b in smap.beats
                if b.id not in kept
                and b.id not in forbidden
                and lo + span * 0.2 <= b.start
                and b.end <= hi - span * 0.2 + 1
            ]
            mid.sort(
                key=lambda b: (
                    tuple(-x for x in score(b)),
                    abs((b.start + b.end) / 2 - (lo + hi) / 2),
                )
            )
            before = set(kept)
            if not add_one(mid, upper + params.length_tolerance * target_s):
                break
            protected |= kept - before
            while kept_seconds(kept, by_id) > upper:
                if not remove_one(kept - before):
                    break
    return Selection(kept, over or kept_seconds(kept, by_id) > upper)


def thread_ranks(smap: StoryMap, decisions: dict[str, str]) -> dict[int, int]:
    out: dict[int, int] = {}
    for t in smap.threads:
        rank = THREAD_RANK.get(decisions.get(t["id"], "keep"), 1)
        for bid in t["beats"]:
            out[bid] = max(out.get(bid, 0), rank)
    return out


def parse_select(data: Any, smap: StoryMap) -> tuple[dict[int, int], dict[str, str]]:
    if not isinstance(data, dict) or not isinstance(data.get("beats"), list):
        raise StoryFormatError('the answer needs a "beats" list')
    known = {b.id for b in smap.beats}
    keep: dict[int, int] = {}
    for row in data["beats"]:
        bid = _int(row.get("id")) if isinstance(row, dict) else None
        k = _int(row.get("keep")) if isinstance(row, dict) else None
        if bid in known and k is not None and bid is not None:
            keep[bid] = min(3, max(0, k))
    if len(keep) < len(known) * 0.5:
        raise StoryFormatError(
            f"you scored {len(keep)} of {len(known)} beats; give every beat a keep score"
        )
    decisions = {
        str(t.get("id")): str(t.get("decision"))
        for t in data.get("threads") or []
        if isinstance(t, dict)
    }
    return keep, decisions


def select_step(
    smap: StoryMap, brief: str, fn: ModelFn, rec: Recorder
) -> tuple[dict[int, int], dict[str, str]]:
    user = [
        brief,
        f"Synopsis: {smap.synopsis}",
        "Threads:",
        *(f"- {t['id']} {t['title']}: beats {t['beats']}" for t in smap.threads),
        "Beats (duration, kind, weight, needs):",
        *(
            f"{card(b)} | {int(b.dur)} s, {b.kind}, w{b.weight}, needs {b.needs}"
            for b in smap.beats
        ),
        "Answer with the JSON object the system message describes.",
    ]
    messages = [
        {"role": "system", "content": STORY_SELECT_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
    return rec.ask("select", fn, messages, lambda d, attempt: parse_select(d, smap))


# ---- parts, checks -------------------------------------------------------------------------


def parts_of(
    kept: set[int], smap: StoryMap, params: StoryParams
) -> list[tuple[float, float, list[int]]]:
    """Kept beats as parts `(start_s, end_s, beat ids)`: neighbours closer than `merge_gap_s` join."""
    rows = sorted((b for b in smap.beats if b.id in kept), key=lambda b: b.start)
    parts: list[tuple[float, float, list[int]]] = []
    for b in rows:
        if parts and b.start - parts[-1][1] <= params.merge_gap_s:
            s, _e, ids = parts[-1]
            parts[-1] = (s, max(b.end, parts[-1][1]), [*ids, b.id])
        else:
            parts.append((b.start, b.end, [b.id]))
    return parts


def overlap_frac(a: float, b: float, parts: list[tuple[float, float]]) -> float:
    if b <= a:
        return 0.0
    got = sum(max(0.0, min(b, pe) - max(a, ps)) for ps, pe in parts)
    return got / (b - a)


def run_checks(
    kept: set[int],
    smap: StoryMap,
    target_s: float | None,
    duration_s: float,
    params: StoryParams,
    *,
    over_target: bool = False,
) -> dict[str, Any]:
    """Automatic checks A1 to A8 of the plan (2.8); `hard_ok` is true when every hard one passes."""
    by_id = {b.id: b for b in smap.beats}
    total_s = kept_seconds(kept, by_id)
    a1 = sorted((i, n) for i in kept for n in by_id[i].needs if n not in kept)
    end_closure = closure(set(smap.ending), by_id)
    shares = quarter_shares(kept, smap, duration_s, params)
    overall = total_s / sum(b.dur for b in smap.beats)
    gaps = skips(kept, smap)
    longest = max((hi - lo for lo, hi in gaps), default=0.0)
    needed = {n for i in kept for n in by_id[i].needs}
    dangling = [i for i in kept if by_id[i].kind == "setup" and i not in needed]
    film_w = sum(b.weight * b.dur for b in smap.beats) / sum(b.dur for b in smap.beats)
    kept_w = sum(by_id[i].weight * by_id[i].dur for i in kept) / total_s if total_s else 0.0
    a3 = True
    if target_s:
        a3 = over_target or abs(total_s - target_s) <= target_s * params.length_tolerance
    checks = {
        "A1_closure_violations": len(a1),
        "A2_ending_kept": end_closure <= kept,
        "A3_length_in_band": a3,
        "A4_quarter_shares": [round(s, 2) for s in shares],
        "A4_lowest_ratio": round(min(shares) / overall, 2) if overall else 0.0,
        "A5_longest_skip_s": int(longest),
        "A6_dangling_setups": len(dangling),
        "A7_weight_ratio": round(kept_w / film_w, 2) if film_w else 0.0,
        "A8_boundaries_ok": True,
        "kept_s": int(total_s),
        "over_target": over_target,
    }
    checks["hard_ok"] = bool(
        checks["A1_closure_violations"] == 0 and checks["A2_ending_kept"] and a3
    )
    return checks


def pair_results(
    pairs: list[dict[str, Any]], kept: set[int], smap: StoryMap, params: StoryParams
) -> list[dict[str, Any]]:
    """Each pair (cause range, result range in seconds): handled when both are kept or both are cut."""
    parts = [(s, e) for s, e, _ in parts_of(kept, smap, params)]
    out = []
    for p in pairs:
        fc = overlap_frac(p["cause"][0], p["cause"][1], parts)
        fr = overlap_frac(p["result"][0], p["result"][1], parts)
        out.append(
            {
                "id": p["id"],
                "cause_kept": round(fc, 2),
                "result_kept": round(fr, 2),
                "handled": (fc >= 0.5) == (fr >= 0.5),
            }
        )
    return out


# ---- step 4: critic and repair -------------------------------------------------------------


def viewer_text(kept: set[int], smap: StoryMap, units: list[Unit]) -> str:
    """The cut as the viewer gets it, with a skip line at each seam."""
    rows = sorted((b for b in smap.beats if b.id in kept), key=lambda b: b.start)
    out: list[str] = []
    prev_end = 0.0
    for b in rows:
        if out and b.start - prev_end > 1:
            out.append(f"--- skipped {fmt_ts(b.start - prev_end)} ---")
        out.append(f"[B{b.id}]")
        out.extend(u.text for u in units if b.first <= u.n <= b.last and not is_music(u))
        prev_end = b.end
    return "\n".join(out)


def parse_critic(data: Any, smap: StoryMap) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise StoryFormatError("the answer must be a JSON object")
    scores = {}
    for key in ("consistency", "density", "goal"):
        v = data.get(key)
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise StoryFormatError(f'"{key}" must be a number from 0 to 10')
        scores[key] = min(10.0, max(0.0, float(v)))
    known = {b.id for b in smap.beats}
    problems = []
    for p in data.get("problems") or []:
        if not isinstance(p, dict):
            continue
        problems.append(
            {
                "at_beat": _int(p.get("at_beat")),
                "type": p.get("type") if p.get("type") in CRITIC_TYPES else "goal",
                "note": str(p.get("note") or "")[:120],
                "add": [n for n in (_int(x) for x in p.get("add") or []) if n in known],
                "drop": [n for n in (_int(x) for x in p.get("drop") or []) if n in known],
            }
        )
    return {**scores, "problems": problems}


def critic_step(
    smap: StoryMap,
    units: list[Unit],
    kept: set[int],
    brief: str,
    fn: ModelFn,
    rec: Recorder,
) -> dict[str, Any]:
    user = [
        brief,
        "The cut:",
        viewer_text(kept, smap, units),
        "=== skipped beats ===",
        *(card(b) for b in smap.beats if b.id not in kept),
        "Answer with the JSON object the system message describes.",
    ]
    messages = [
        {"role": "system", "content": STORY_CRITIC_SYSTEM},
        {"role": "user", "content": "\n".join(user)},
    ]
    return rec.ask("critic", fn, messages, lambda d, attempt: parse_critic(d, smap))


def accepted(review: dict[str, Any], checks: dict[str, Any], params: StoryParams) -> bool:
    return bool(
        checks["hard_ok"]
        and review["consistency"] >= params.accept_consistency
        and review["density"] >= params.accept_density
        and review["goal"] >= params.accept_goal
    )


@dataclass
class Round:
    kept: set[int]
    checks: dict[str, Any]
    review: dict[str, Any]
    over_target: bool


@dataclass
class StoryResult:
    smap: StoryMap
    kept: set[int]
    checks: dict[str, Any]
    review: dict[str, Any]
    passed: bool
    rounds: list[Round]
    keep: dict[int, int]
    thread_decisions: dict[str, str]
    calls: list[CallRecord]
    target_s: int
    duration_s: float
    purpose: str


def run_selection(
    smap: StoryMap,
    units: list[Unit],
    purpose: str,
    target_s: int,
    duration_s: float,
    select_fn: ModelFn,
    critic_fn: ModelFn,
    params: StoryParams,
    rec: Recorder,
) -> StoryResult:
    """Steps 3 and 4: the model scores, code builds, the critic reads, code repairs (at most
    `repair_rounds`); the best round by (hard checks, consistency, goal, density) is the result."""
    brief = purpose_brief(purpose, target_s, duration_s)
    keep, decisions = select_step(smap, brief, select_fn, rec)
    ranks = thread_ranks(smap, decisions)
    by_id = {b.id: b for b in smap.beats}
    forced: set[int] = set()
    forbidden: set[int] = set()
    rounds: list[Round] = []
    for attempt in range(params.repair_rounds + 1):
        sel = select_beats(
            smap, keep, ranks, target_s, duration_s, params, forced=forced, forbidden=forbidden
        )
        checks = run_checks(
            sel.kept, smap, target_s, duration_s, params, over_target=sel.over_target
        )
        review = critic_step(smap, units, sel.kept, brief, critic_fn, rec)
        rounds.append(Round(sel.kept, checks, review, sel.over_target))
        if accepted(review, checks, params) or attempt == params.repair_rounds:
            break
        needed = {n for i in sel.kept for n in by_id[i].needs}
        for p in review["problems"]:
            forced |= {i for i in p["add"] if i not in sel.kept}
            forbidden |= {i for i in p["drop"] if i in sel.kept and i not in needed}
        forced -= forbidden
    best = max(
        rounds,
        key=lambda r: (
            r.checks["hard_ok"],
            r.review["consistency"],
            r.review["goal"],
            r.review["density"],
        ),
    )
    return StoryResult(
        smap=smap,
        kept=best.kept,
        checks=best.checks,
        review=best.review,
        passed=accepted(best.review, best.checks, params),
        rounds=rounds,
        keep=keep,
        thread_decisions=decisions,
        calls=rec.calls,
        target_s=target_s,
        duration_s=duration_s,
        purpose=purpose,
    )


# ---- what the owner reads ------------------------------------------------------------------


def skip_notes(kept: set[int], smap: StoryMap, params: StoryParams) -> dict[int, str]:
    """Per kept beat that follows a skip of `skip_note_min_s` or more: what was skipped (weight >= 3)."""
    by_start = sorted(smap.beats, key=lambda b: b.start)
    notes: dict[int, str] = {}
    last_kept_end: float | None = None
    skipped: list[Beat] = []
    for b in by_start:
        if b.id in kept:
            if skipped and last_kept_end is not None:
                span = b.start - last_kept_end
                if span >= params.skip_note_min_s:
                    text = "; ".join(s.what for s in skipped if s.weight >= 3)
                    notes[b.id] = text[:120]
            skipped, last_kept_end = [], b.end
        else:
            skipped.append(b)
    return notes


def render_text(res: StoryResult, params: StoryParams, label: str) -> str:
    parts = parts_of(res.kept, res.smap, params)
    kept_s = res.checks["kept_s"]
    lines = [
        f"Paper cut: {label}",
        f"Purpose: {res.purpose}",
        f"Kept {fmt_ts(kept_s)} of {fmt_ts(res.duration_s)} (target {fmt_ts(res.target_s)}), "
        f"{len(parts)} parts. Longest skip {fmt_ts(res.checks['A5_longest_skip_s'])}.",
        f"Critic: consistency {res.review['consistency']:g}, density {res.review['density']:g}, "
        f"goal {res.review['goal']:g}; {'accepted' if res.passed else 'not accepted'}.",
        "",
    ]
    by_id = {b.id: b for b in res.smap.beats}
    for s, e, ids in parts:
        lines.append(f"KEEP {fmt_ts(s)}-{fmt_ts(e)}")
        lines.extend(f"    {fmt_ts(by_id[i].start)} {by_id[i].what}" for i in ids)
    return "\n".join(lines) + "\n"


PAGE_CSS = (
    "body{font:16px/1.45 system-ui,sans-serif;max-width:46rem;margin:1rem auto;padding:0 1rem;"
    "color:#1b1b1b;background:#fff}h1{font-size:1.3rem}h2{font-size:1.1rem;margin-top:2rem}"
    ".beat{display:flex;gap:.6rem;padding:.35rem .5rem;border-radius:6px;margin:2px 0}"
    ".keep{background:#e4f3e4}.skip{background:#f1f1f1;color:#777}.t{font-variant-numeric:"
    "tabular-nums;min-width:4.2rem}.mark{margin-left:auto;white-space:nowrap}"
    ".note{font-size:.85rem;color:#555;margin:.2rem .5rem}"
    "@media (prefers-color-scheme:dark){body{background:#161616;color:#e6e6e6}"
    ".keep{background:#1d3a1d}.skip{background:#232323;color:#999}.note{color:#aaa}}"
)

PAGE_JS = (
    "const k='papercut-marks';let m={};try{m=JSON.parse(localStorage.getItem(k)||'{}')}catch(e){}"
    "function save(){try{localStorage.setItem(k,JSON.stringify(m))}catch(e){}}"
    "document.querySelectorAll('[data-b]').forEach(el=>{const id=el.dataset.b;const cb="
    "el.querySelector('input');if(!cb)return;cb.checked=!!m[id];cb.onchange=()=>{m[id]="
    "cb.checked;save()}});"
    "document.getElementById('copy').onclick=()=>{const rows=[];document.querySelectorAll('[data-b]')"
    ".forEach(el=>{const cb=el.querySelector('input');if(cb&&cb.checked)rows.push(el.dataset.kind+' '"
    "+el.dataset.b)});navigator.clipboard.writeText(rows.join('\\n'))};"
)


def render_html(results: list[tuple[str, StoryResult]], params: StoryParams, title: str) -> str:
    """One static page: per candidate the beats in order, kept solid, skipped greyed with their
    duration; tick a skipped beat that was needed or a kept beat that was filler."""
    esc = html.escape
    out = [
        "<!doctype html><html><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{esc(title)}</title><style>{PAGE_CSS}</style></head><body><h1>{esc(title)}</h1>",
        "<p>Green = kept, grey = skipped. Tick a grey beat you needed (<b>needed</b>) or a green "
        "beat that was filler (<b>filler</b>). <button id=copy>Copy my marks</button></p>",
    ]
    for label, res in results:
        notes = skip_notes(res.kept, res.smap, params)
        c, r = res.checks, res.review
        out.append(
            f"<h2>{esc(label)}: {fmt_ts(c['kept_s'])} of {fmt_ts(res.duration_s)}</h2>"
            f"<p>Longest skip {fmt_ts(c['A5_longest_skip_s'])}. Critic: consistency "
            f"{r['consistency']:g}, density {r['density']:g}, goal {r['goal']:g}.</p>"
        )
        for b in res.smap.beats:
            kept = b.id in res.kept
            kind = "filler" if kept else "needed"
            key = f"{label}-{b.id}"
            if b.id in notes:
                out.append(f"<div class=note>skipped before this: {esc(notes[b.id])}</div>")
            tag = "" if kept else f" ({int(b.dur)} s)"
            out.append(
                f"<div class='beat {'keep' if kept else 'skip'}' data-b='{esc(key)}' "
                f"data-kind='{kind}'><span class=t>{fmt_ts(b.start)}</span><span>{esc(b.what)}"
                f"{tag}</span><label class=mark><input type=checkbox> {kind}</label></div>"
            )
    out.append(f"<script>{PAGE_JS}</script></body></html>")
    return "\n".join(out)
