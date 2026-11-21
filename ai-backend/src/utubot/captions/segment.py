from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..config import CaptionsConfig
from .chunking import bare
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


def retime_split(
    text: str, start: float, end: float, cfg: CaptionsConfig, *, char_timed: bool = True
) -> list[Cue]:
    """Text too long for one cue, cut into timed cues: lines first, then cues of `max_lines`.

    Time is shared by character count, so a cue lasts as long as its text is long; the last cue
    ends exactly at `end`. `char_timed=False` for a caption row's own span (the times are the
    caption's, only the cut between them is by characters).
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
        out.append(Cue(cursor, cue_end, list(group), char_timed=char_timed))
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


def tokens_match(text: str, words: list[Word]) -> bool:
    """Whether `text` (a speaker prefix token aside) is the words' own text, up to case and punctuation."""
    tokens = text.split()
    spoken = [w for w in words if w.text.strip()]
    if (
        tokens
        and SPEAKER_TOKEN_RE.match(tokens[0])
        and spoken
        and spoken[0].text.strip() != tokens[0]
    ):
        tokens = tokens[1:]
    return [bare(t) for t in tokens] == [bare(w.text) for w in spoken]


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


def split_cue(
    cue: Cue,
    text: str,
    cfg: CaptionsConfig,
    stats: SplitStats,
    room_end: float | None = None,
) -> list[Cue]:
    """`text` (a corrected or translated version of the cue) cut into cues that fit the limits.

    With the cue's words the cut lands on word boundaries: where the text still maps one token to
    one word the groups take their own words' times (`exact`), otherwise each cut goes to the
    widest pause near the text's share of the cue's time (`at_pause`). A piece runs from its first
    word's start to its last word's end, lingers `cue_linger_s` and is stretched to `min_cue_s`
    only into the gap before the next piece; the first piece starts and the last ends where the cue
    does; a last piece shorter than `min_cue_s` is stretched too, but only up to `room_end` (the next
    cue's start; no stretch when unknown). A cue without enough words is cut by character count (`by_chars`).
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
    match = cue.words_match_text and tokens_match(text, words)
    if match:
        cuts = _boundaries_exact(counts, prefix)
        stats.exact += 1
    else:
        weights = [sum(len(line) for line in group) + len(group) for group in groups]
        cuts = _boundaries_at_pause(weights, words, cfg)
        stats.at_pause += 1
    edges = [0, *cuts, len(words)]
    n = len(groups)
    starts = [cue.start, *(words[edges[i]].start for i in range(1, n))]
    ends = [*(words[edges[i + 1] - 1].end for i in range(n - 1)), cue.end]
    starts = _clamped_starts(starts, cue, cfg)
    pieces: list[Cue] = []
    for i, group in enumerate(groups):
        if i < n - 1:
            room = starts[i + 1]
            end = min(max(ends[i] + cfg.cue_linger_s, starts[i] + cfg.min_cue_s), room)
            end = max(end, min(starts[i] + cfg.word_min_s, room))
        else:
            end = cue.end
        pieces.append(
            Cue(
                starts[i],
                max(end, starts[i]),
                list(group),
                cue.speaker,
                words=words[edges[i] : edges[i + 1]],
                words_match_text=match,
                char_timed=False,
            )
        )
    last = pieces[-1]
    if room_end is not None and last.end - last.start < cfg.min_cue_s:
        last.end = max(last.end, min(last.start + cfg.min_cue_s, room_end))
    return pieces


def _clamped_starts(starts: list[float], cue: Cue, cfg: CaptionsConfig) -> list[float]:
    """Piece starts inside the cue, increasing by at least `word_min_s` (shared evenly if it is too short)."""
    n = len(starts)
    span = cue.end - cue.start
    if span < n * cfg.word_min_s:
        return [cue.start + i * span / n for i in range(n)]
    out: list[float] = []
    for i, start in enumerate(starts):
        low = cue.start + i * cfg.word_min_s
        if out:
            low = max(low, out[-1] + cfg.word_min_s)
        high = cue.end - (n - i) * cfg.word_min_s
        out.append(min(max(start, low), high))
    return out


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


def _joined(first: Cue, second: Cue, cfg: CaptionsConfig) -> Cue | None:
    """The two cues as one, or None when speakers, line limits, `max_cue_s` or `max_cps` forbid it."""
    if first.speaker != second.speaker:
        return None
    text = " ".join([*first.lines, *second.lines])
    lines = wrap_lines(text, cfg.max_chars_per_line, cfg.max_lines)
    start, end = min(first.start, second.start), max(first.end, second.end)
    if lines is None or end - start > cfg.max_cue_s:
        return None
    if cfg.max_cps > 0 and len(text) / max(end - start, 0.1) > cfg.max_cps:
        return None
    if first.words and second.words:
        words, exact = (
            [*first.words, *second.words],
            first.words_match_text and second.words_match_text,
        )
    else:
        # a cue without words (a caption row) joined to one with: the words stay, the text no longer maps onto them
        words, exact = first.words or second.words, False
    return Cue(start, end, lines, first.speaker, words=words, words_match_text=exact)


def merge_short(cues: list[Cue], cfg: CaptionsConfig) -> tuple[list[Cue], int]:
    """Join each speech cue shorter than `min_cue_s` to a neighbour within `sentence_gap_s`.

    The previous cue is preferred unless it ends a sentence and the next one follows without a
    pause; a join must still wrap, stay within `max_cue_s` and `max_cps` and keep one speaker.
    Returns the cues and how many were joined.
    """
    from .align import is_non_speech

    out: list[Cue] = []
    pending = list(cues)
    merged = 0
    for i, cue in enumerate(pending):
        if cue.end - cue.start >= cfg.min_cue_s or is_non_speech(cue):
            out.append(cue)
            continue
        before = out[-1] if out and not is_non_speech(out[-1]) else None
        after = (
            pending[i + 1] if i + 1 < len(pending) and not is_non_speech(pending[i + 1]) else None
        )
        near_before = before is not None and cue.start - before.end <= cfg.sentence_gap_s
        near_after = after is not None and after.start - cue.end <= cfg.sentence_gap_s
        sentence_over = before is not None and " ".join(before.lines).endswith(SENTENCE_END)
        order = ["before", "after"] if not (sentence_over and near_after) else ["after", "before"]
        for choice in order:
            if choice == "before" and near_before:
                joined = _joined(before, cue, cfg)
                if joined is not None:
                    out[-1] = joined
                    merged += 1
                    break
            if choice == "after" and near_after:
                joined = _joined(cue, after, cfg)
                if joined is not None:
                    pending[i + 1] = joined
                    merged += 1
                    break
        else:
            out.append(cue)
    return out, merged


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
