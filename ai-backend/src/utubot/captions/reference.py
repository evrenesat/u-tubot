"""Check the engine's word times against YouTube's own (pure functions).

YouTube's automatic captions carry a start per word. They are not the truth (rows lead speech by about
a quarter of a second) but they are an independent clock: where the engine's words and the reference's
words are the same tokens, the difference of their starts says whether the engine is where YouTube
heard the speech. The check changes no times; it measures and locates (`Agreement.regions`).
"""

from __future__ import annotations

import bisect
import difflib
import statistics
import unicodedata
from dataclasses import dataclass, field

from ..config import CaptionsConfig
from .chunking import bare
from .syncscore import PERCENTILE_HIGH, PERCENTILE_LOW, SECONDS_DIGITS, SHARE_DIGITS, percentile
from .types import TIMING_INTERPOLATED, Word

SOURCE_WORDS = "words"
SOURCE_ROWS = "rows"
REASON_NO_REFERENCE = "no_reference"
REASON_TOO_FEW = "too_few_anchors"
REASON_OTHER_SCRIPT = "other_script"


@dataclass
class Agreement:
    anchors: int
    anchor_share: float  # matched reference tokens / reference tokens
    median_s: float  # word start - reference start: the reference's lead, with its sign
    p10_s: float
    p90_s: float
    within_s: float  # share of pairs within `ref_agree_s` of the median
    regions: list[tuple[float, float, float]] = field(default_factory=list)  # (start, end, median)
    source: str = SOURCE_WORDS

    def as_detail(self) -> dict[str, object]:
        return {
            "anchors": self.anchors,
            "anchor_share": round(self.anchor_share, SHARE_DIGITS),
            "median_s": round(self.median_s, SECONDS_DIGITS),
            "p10_s": round(self.p10_s, SECONDS_DIGITS),
            "p90_s": round(self.p90_s, SECONDS_DIGITS),
            "within_s": round(self.within_s, SHARE_DIGITS),
            "regions": [
                [round(a, SECONDS_DIGITS), round(b, SECONDS_DIGITS), round(m, SECONDS_DIGITS)]
                for a, b, m in self.regions
            ],
            "source": self.source,
        }


@dataclass
class Check:
    """The verdict of one job's check: `skipped` carries a reason, the others an agreement."""

    status: str  # "ok" | "warn" | "skipped"
    reason: str | None = None
    agreement: Agreement | None = None
    reference_words: int = 0

    @property
    def lead_s(self) -> float:
        """YouTube's lead over the engine as a time to add to reference words (0 when unknown)."""
        return self.agreement.median_s if self.agreement and self.status != "skipped" else 0.0


STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_SKIPPED = "skipped"


def script_latin_share(texts: list[str]) -> float:
    """Share of the texts whose letters are all Latin (0 for none with letters)."""
    letters = [[ch for ch in text if ch.isalpha()] for text in texts]
    letters = [chars for chars in letters if chars]
    if not letters:
        return 0.0
    latin = sum(
        1
        for chars in letters
        if all(ch.isascii() or "LATIN" in unicodedata.name(ch, "") for ch in chars)
    )
    return latin / len(letters)


def _block_starts(end_s: float, cfg: CaptionsConfig) -> list[float]:
    step = max(cfg.ref_block_s - cfg.ref_block_overlap_s, cfg.ref_block_s / 2)
    starts, at = [], 0.0
    while at <= end_s:
        starts.append(at)
        at += step
    return starts


def anchors(
    ref: list[tuple[float, str]], words: list[Word], cfg: CaptionsConfig
) -> list[tuple[float, float]]:
    """`(ref_start, word_start)` pairs for tokens both sides have, in time order.

    Works in blocks of `ref_block_s`: inside a block the two token lists are aligned with
    `SequenceMatcher`; a matching run counts with at least `ref_min_run` tokens, or one token that
    is unique in both lists of the block. Pairs further apart than `ref_max_offset_s` are dropped.
    Interpolated words (no real engine time) never anchor.
    """
    ref_items = sorted((t, bare(text)) for t, text in ref)
    ref_items = [(t, tok) for t, tok in ref_items if tok]
    real = sorted((w for w in words if w.timing != TIMING_INTERPOLATED), key=lambda w: w.start)
    own_items = [(w.start, bare(w.text)) for w in real]
    own_items = [(t, tok) for t, tok in own_items if tok]
    if not ref_items or not own_items:
        return []
    ref_times = [t for t, _ in ref_items]
    own_times = [t for t, _ in own_items]
    pairs: dict[int, tuple[float, float]] = {}
    reach = cfg.ref_max_offset_s
    for begin in _block_starts(ref_times[-1], cfg):
        end = begin + cfg.ref_block_s
        a_lo, a_hi = bisect.bisect_left(ref_times, begin), bisect.bisect_left(ref_times, end)
        b_lo = bisect.bisect_left(own_times, begin - reach)
        b_hi = bisect.bisect_left(own_times, end + reach)
        left = [tok for _, tok in ref_items[a_lo:a_hi]]
        right = [tok for _, tok in own_items[b_lo:b_hi]]
        if not left or not right:
            continue
        matcher = difflib.SequenceMatcher(None, left, right, autojunk=False)
        for block in matcher.get_matching_blocks():
            if block.size < cfg.ref_min_run and not _unique_in(left, right, block):
                continue
            for k in range(block.size):
                ref_at, own_at = a_lo + block.a + k, b_lo + block.b + k
                gap = own_times[own_at] - ref_times[ref_at]
                if abs(gap) <= reach:
                    pairs[ref_at] = (ref_times[ref_at], own_times[own_at])
    return [pairs[i] for i in sorted(pairs)]


def _unique_in(left: list[str], right: list[str], block: difflib.Match) -> bool:
    if block.size != 1:
        return False
    token = left[block.a]
    return left.count(token) == 1 and right.count(token) == 1


def row_anchors(
    rows: list[tuple[float, float, str]], words: list[Word], cfg: CaptionsConfig
) -> list[tuple[float, float]]:
    """The fallback without YouTube word times: each caption row's first token and the nearest
    engine word with that token within `ref_max_offset_s` of the row start."""
    real = sorted((w for w in words if w.timing != TIMING_INTERPOLATED), key=lambda w: w.start)
    by_token: dict[str, list[float]] = {}
    for w in real:
        by_token.setdefault(bare(w.text), []).append(w.start)
    out: list[tuple[float, float]] = []
    for start, _end, text in sorted(rows):
        first = next((bare(tok) for tok in text.split() if bare(tok)), "")
        starts = by_token.get(first)
        if not starts:
            continue
        at = bisect.bisect_left(starts, start)
        near = [starts[j] for j in (at - 1, at) if 0 <= j < len(starts)]
        best = min(near, key=lambda t: abs(t - start))
        if abs(best - start) <= cfg.ref_max_offset_s:
            out.append((start, best))
    return out


def _regions(
    pairs: list[tuple[float, float]], offsets: list[float], median: float, cfg: CaptionsConfig
) -> list[tuple[float, float, float]]:
    k = cfg.ref_region_min_anchors
    if len(pairs) < k:
        return []
    half = k // 2
    deviant = []
    for i in range(len(offsets)):
        window = offsets[max(0, i - half) : i + half + 1]
        deviant.append(abs(statistics.median(window) - median) > cfg.ref_region_off_s)
    out: list[tuple[float, float, float]] = []
    i = 0
    while i < len(pairs):
        if not deviant[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(pairs) and deviant[j + 1]:
            j += 1
        if j - i + 1 >= k:
            lo, hi = i, j
            while lo > 0 and abs(offsets[lo - 1] - median) > cfg.ref_region_off_s:
                lo -= 1
            while hi + 1 < len(pairs) and abs(offsets[hi + 1] - median) > cfg.ref_region_off_s:
                hi += 1
            out.append((pairs[lo][0], pairs[hi][0], statistics.median(offsets[lo : hi + 1])))
            i = hi + 1
        else:
            i = j + 1
    return out


def agreement(
    pairs: list[tuple[float, float]], total: int, cfg: CaptionsConfig, source: str = SOURCE_WORDS
) -> Agreement:
    """How the engine's starts differ from the reference's over `pairs` (`total` reference tokens)."""
    offsets = [own - ref for ref, own in pairs]
    if not offsets:
        return Agreement(0, 0.0, 0.0, 0.0, 0.0, 0.0, [], source)
    median = statistics.median(offsets)
    ordered = sorted(offsets)
    within = sum(1 for o in offsets if abs(o - median) <= cfg.ref_agree_s)
    return Agreement(
        len(offsets),
        len(offsets) / total if total else 0.0,
        median,
        percentile(ordered, PERCENTILE_LOW),
        percentile(ordered, PERCENTILE_HIGH),
        within / len(offsets),
        _regions(pairs, offsets, median, cfg),
        source,
    )


def check(
    ref_words: list[tuple[float, str]] | None,
    rows: list[tuple[float, float, str]],
    words: list[Word],
    cfg: CaptionsConfig,
) -> Check:
    """The per-job agreement check: YouTube's word times when it has them, else its caption rows."""
    if ref_words:
        texts, source = [text for _t, text in ref_words], SOURCE_WORDS
    elif rows:
        texts, source = [text for _s, _e, text in rows], SOURCE_ROWS
    else:
        return Check(STATUS_SKIPPED, REASON_NO_REFERENCE)
    own = [w.text for w in words if w.timing != TIMING_INTERPOLATED]
    if not own:
        return Check(STATUS_SKIPPED, REASON_NO_REFERENCE, reference_words=len(texts))
    gap = abs(script_latin_share(texts) - script_latin_share(own))
    if gap > cfg.ref_script_gap_share:
        return Check(STATUS_SKIPPED, REASON_OTHER_SCRIPT, reference_words=len(texts))
    if source == SOURCE_WORDS:
        pairs = anchors(ref_words or [], words, cfg)
    else:
        pairs = row_anchors(rows, words, cfg)
    result = agreement(pairs, len(texts), cfg, source)
    if result.anchor_share < cfg.ref_min_anchor_share:
        return Check(STATUS_SKIPPED, REASON_TOO_FEW, result, len(texts))
    return Check(STATUS_WARN if result.regions else STATUS_OK, None, result, len(texts))
