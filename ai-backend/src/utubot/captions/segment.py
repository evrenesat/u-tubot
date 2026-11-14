from __future__ import annotations

from ..config import CaptionsConfig
from .types import Cue, Word

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CLAUSE_END = (",", ";", ":", "—", "、", "，")
CLAUSE_SPLIT_FRACTION = 0.6
SPEAKER_PREFIX_FMT = "[{}] "


def wrap_lines(text: str, max_chars: int, max_lines: int) -> list[str] | None:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines or any(len(line) > max_chars for line in lines):
        return None
    if len(lines) == 2 and len(lines[1]) < len(lines[0]) // 3:
        balanced = _balance(words, max_chars)
        if balanced:
            return balanced
    return lines


def _balance(words: list[str], max_chars: int) -> list[str] | None:
    best: list[str] | None = None
    best_gap = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        if len(a) <= max_chars and len(b) <= max_chars:
            gap = abs(len(a) - len(b))
            if best_gap is None or gap < best_gap:
                best, best_gap = [a, b], gap
    return best


def speaker_label(raw: str | None, order: dict[str, int]) -> str | None:
    if raw is None:
        return None
    if raw not in order:
        order[raw] = len(order) + 1
    return f"S{order[raw]}"


def build_cues(words: list[Word], cfg: CaptionsConfig) -> list[Cue]:
    words = [w for w in words if w.text.strip()]
    order: dict[str, int] = {}
    cues: list[Cue] = []
    cue_speakers: list[str | None] = []
    current: list[Word] = []

    def prefix_for(raw: str | None) -> str:
        if raw is None or (cue_speakers and cue_speakers[-1] == raw):
            return ""
        return SPEAKER_PREFIX_FMT.format(speaker_label(raw, order))

    def text_of(ws: list[Word]) -> str:
        return prefix_for(ws[0].speaker) + " ".join(w.text.strip() for w in ws)

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = text_of(current)
        lines = wrap_lines(text, cfg.max_chars_per_line, cfg.max_lines) or [text]
        raw = current[0].speaker
        cues.append(
            Cue(
                current[0].start,
                max(current[-1].end, current[0].start),
                lines,
                speaker_label(raw, order),
            )
        )
        cue_speakers.append(raw)
        current = []

    capacity = cfg.max_chars_per_line * cfg.max_lines
    for word in words:
        if current:
            last = current[-1]
            cur_dur = last.end - current[0].start
            joined = text_of(current)
            last_text = last.text.rstrip()
            if (
                word.speaker != last.speaker
                or word.start - last.end > cfg.sentence_gap_s
                or word.end - current[0].start > cfg.max_cue_s
                or wrap_lines(
                    f"{joined} {word.text.strip()}", cfg.max_chars_per_line, cfg.max_lines
                )
                is None
                or (last_text.endswith(SENTENCE_END) and cur_dur >= cfg.min_cue_s)
                or (
                    last_text.endswith(CLAUSE_END)
                    and cur_dur >= cfg.min_cue_s
                    and len(joined) >= capacity * CLAUSE_SPLIT_FRACTION
                )
                or (
                    cfg.max_cps > 0
                    and cur_dur >= cfg.min_cue_s
                    and len(f"{joined} {word.text.strip()}".lstrip())
                    / max(word.end - current[0].start, 0.1)
                    > cfg.max_cps
                )
            ):
                flush()
        current.append(word)
    flush()
    return enforce_timing(cues, cfg)


def forced_lines(words: list[str], max_chars: int) -> list[str]:
    """Greedy line packing that never fails: a word longer than `max_chars` keeps its own line."""
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def retime_split(text: str, start: float, end: float, cfg: CaptionsConfig) -> list[Cue]:
    """Text too long for one cue, cut into timed cues: lines first, then cues of `max_lines`.

    Time is shared by character count, so a cue lasts as long as its text is long; the last cue
    ends exactly at `end`.
    """
    tokens = text.split()
    if not tokens:
        return []
    lines = forced_lines(tokens, cfg.max_chars_per_line)
    groups = [lines[i : i + cfg.max_lines] for i in range(0, len(lines), cfg.max_lines)]
    weights = [sum(len(line) for line in group) + len(group) for group in groups]
    span = max(end - start, 0.2 * len(groups))
    total = sum(weights) or 1
    out: list[Cue] = []
    cursor = start
    for i, group in enumerate(groups):
        if i == len(groups) - 1:
            cue_end = max(end, cursor + 0.2)
        else:
            cue_end = min(cursor + max(span * weights[i] / total, 0.2), end)
        out.append(Cue(cursor, cue_end, list(group)))
        cursor = cue_end
    return [c for c in out if c.lines]


def enforce_timing(cues: list[Cue], cfg: CaptionsConfig) -> list[Cue]:
    for i, cue in enumerate(cues):
        next_start = cues[i + 1].start if i + 1 < len(cues) else None
        if cue.end - cue.start < cfg.min_cue_s:
            target = cue.start + cfg.min_cue_s
            cue.end = min(target, next_start) if next_start is not None else target
        if cue.end - cue.start > cfg.max_cue_s:
            cue.end = cue.start + cfg.max_cue_s
        if next_start is not None and cue.end > next_start:
            cue.end = next_start
    return [c for c in cues if c.end > c.start]


def fmt_vtt_time(seconds: float) -> str:
    ms_total = int(round(seconds * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def to_vtt(cues: list[Cue]) -> str:
    out = ["WEBVTT", ""]
    for i, cue in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{fmt_vtt_time(cue.start)} --> {fmt_vtt_time(cue.end)}")
        out.extend(cue.lines)
        out.append("")
    return "\n".join(out)


def count_speakers(cues: list[Cue]) -> int:
    return len({c.speaker for c in cues if c.speaker})
