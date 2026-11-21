from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..config import CaptionsConfig
from .types import Cue, Word

SENTENCE_END = (".", "!", "?", "…", "。", "！", "？")
CLAUSE_END = (",", ";", ":", "—", "、", "，")
CLAUSE_SPLIT_FRACTION = 0.6
SPEAKER_PREFIX_FMT = "[{}] "
SPEAKER_TOKEN_RE = re.compile(r"^\[S\d+\]$")


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
                words=list(current),
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
        out.append(Cue(cursor, cue_end, list(group), char_timed=True))
        cursor = cue_end
    return [c for c in out if c.lines]


@dataclass
class SplitStats:
    """How many cues `split_cue` cut at known word ranges, at a pause, or by character count."""

    exact: int = 0
    at_pause: int = 0
    by_chars: int = 0
    overlong: int = 0  # lines still over the limit (a single word longer than the line)

    def as_detail(self) -> dict[str, int]:
        return {
            "split_exact": self.exact,
            "split_at_pause": self.at_pause,
            "split_by_chars": self.by_chars,
            "overlong": self.overlong,
        }


def _group_lines(text: str, cfg: CaptionsConfig) -> tuple[list[str], list[list[str]]]:
    tokens = text.split()
    lines = forced_lines(tokens, cfg.max_chars_per_line)
    groups = [lines[i : i + cfg.max_lines] for i in range(0, len(lines), cfg.max_lines)]
    return tokens, groups


def _boundaries_exact(token_counts: list[int], offset: int) -> list[int]:
    """Word index where each group after the first begins (tokens map one to one onto words)."""
    out, total = [], 0
    for count in token_counts[:-1]:
        total += count
        out.append(total - offset)
    return out


def _boundaries_at_pause(weights: list[int], words: list[Word], cfg: CaptionsConfig) -> list[int]:
    """Word index where each group after the first begins: the widest pause near the text share.

    The target is the time fraction equal to the characters of the groups so far; boundaries within
    `split_search_frac` of it compete on the gap before the word (the nearest wins a tie); when none
    is in range the nearest boundary is taken. Boundaries stay increasing and leave one word per
    remaining group.
    """
    begin, finish = words[0].start, words[-1].end
    span = max(finish - begin, 1e-9)
    total = sum(weights)
    out: list[int] = []
    done = 0
    previous = 0
    n = len(weights)
    for i in range(n - 1):
        done += weights[i]
        target = done / total
        low, high = previous + 1, len(words) - (n - 1 - i)
        near: list[tuple[float, int]] = []
        for b in range(low, high + 1):
            time_frac = ((words[b - 1].end + words[b].start) / 2 - begin) / span
            near.append((abs(time_frac - target), b))
        in_range = [(d, b) for d, b in near if d <= cfg.split_search_frac]
        if in_range:
            _, best = max(
                in_range, key=lambda item: (words[item[1]].start - words[item[1] - 1].end, -item[0])
            )
        else:
            best = min(near)[1]
        out.append(best)
        previous = best
    return out


def split_cue(cue: Cue, text: str, cfg: CaptionsConfig, stats: SplitStats) -> list[Cue]:
    """`text` (a corrected or translated version of the cue) cut into cues that fit the limits.

    With the cue's words the cut lands on word boundaries: where the text still maps one token to
    one word the groups take their own words' times (`exact`), otherwise each cut goes to the
    widest pause near the text's share of the cue's time (`at_pause`). A piece runs from its first
    word's start to its last word's end, lingers `cue_linger_s` and is stretched to `min_cue_s`
    only into the gap before the next piece; the first piece starts and the last ends where the cue
    does. A cue without enough words is cut by character count (`by_chars`).
    """
    tokens, groups = _group_lines(text, cfg)
    if not tokens:
        return []
    stats.overlong += sum(len(line) > cfg.max_chars_per_line for g in groups for line in g)
    words = [w for w in (cue.words or []) if w.text.strip()]
    if len(groups) == 1:
        return [replace(cue, lines=list(groups[0]), words=cue.words)]
    if len(words) < len(groups):
        stats.by_chars += 1
        pieces = retime_split(text, cue.start, cue.end, cfg)
        return [
            replace(p, speaker=cue.speaker, words=None, words_match_text=cue.words_match_text)
            for p in pieces
        ]
    counts = [sum(len(line.split()) for line in group) for group in groups]
    prefix = 1 if SPEAKER_TOKEN_RE.match(tokens[0]) and words[0].text.strip() != tokens[0] else 0
    if cue.words_match_text and len(tokens) - prefix == len(words):
        cuts = _boundaries_exact(counts, prefix)
        stats.exact += 1
    else:
        weights = [sum(len(line) for line in group) + len(group) for group in groups]
        cuts = _boundaries_at_pause(weights, words, cfg)
        stats.at_pause += 1
    edges = [0, *cuts, len(words)]
    pieces: list[Cue] = []
    for i, group in enumerate(groups):
        part = words[edges[i] : edges[i + 1]]
        start = cue.start if i == 0 else part[0].start
        end = cue.end if i == len(groups) - 1 else part[-1].end
        pieces.append(
            Cue(
                start,
                max(end, start),
                list(group),
                cue.speaker,
                words=part,
                words_match_text=cue.words_match_text,
                char_timed=False,
            )
        )
    for i, piece in enumerate(pieces[:-1]):
        room = pieces[i + 1].start
        piece.end = min(max(piece.end + cfg.cue_linger_s, piece.start + cfg.min_cue_s), room)
    return pieces


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


def pad_cues(cues: list[Cue], cfg: CaptionsConfig) -> list[Cue]:
    """Let each cue linger `cue_linger_s` past its last word, never into the next cue or past `max_cue_s`.

    The linger counts from the last word's end (the cue's own end when it holds no words), so a cue
    that already ends later (stretched to `min_cue_s`, snapped to a silence) is not pushed further.
    """
    for i, cue in enumerate(cues):
        anchor = cue.words[-1].end if cue.words else cue.end
        limit = anchor + cfg.cue_linger_s
        if i + 1 < len(cues):
            limit = min(limit, cues[i + 1].start)
        limit = min(limit, cue.start + cfg.max_cue_s)
        cue.end = max(cue.end, limit)
    return cues


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
