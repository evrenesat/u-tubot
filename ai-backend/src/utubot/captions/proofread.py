"""The LLM proofreading pass of the caption pipeline.

Raw ASR text and YouTube's auto captions miss punctuation and capitalisation, and misspell names.
`Proofreader.polish` sends batches of cue texts to the LLM (the `[llm.captions]` model) together
with the video's title and description, and merges the corrected texts back into the cues. The
answer must be a JSON array of the same length as the batch; anything else - and any batch whose
text suddenly grows beyond `proofread_max_ratio` (a sign of invention) or shrinks below
`1 / proofread_max_ratio` (dropped content) - falls back to the original texts. A failing LLM
never fails the job: the cues keep their unproofread text and the stage warns.

Corrected texts are re-wrapped to the line limits; text that no longer fits one cue is re-split
into several timed cues (`segment.retime_split`), so the stored cues never break the limits.

Corrected batches are cached per video (`StageCache`), so a retried job does not pay for the same
proofreading twice.
"""

from __future__ import annotations

import hashlib
import json

from ..config import CaptionsConfig, LLMTask
from ..llm import LLMClient
from . import events
from .segment import retime_split, wrap_lines
from .stages import StageCache
from .types import Cue

PROOFREAD_SYSTEM = (
    "You proofread subtitle cues written in {lang}. Fix punctuation, capitalisation and spelling. "
    "Correct names and technical terms using the video's title and description. Keep the meaning "
    "and the wording of every cue; never merge, split, reorder, translate or add cues. "
    "Return ONLY a JSON array of strings with the same length and order as the input list."
)


class Proofreader:
    def __init__(
        self,
        llm: LLMClient | None,
        cfg: CaptionsConfig,
        task: LLMTask,
        cache: StageCache | None = None,
    ):
        self.llm = llm
        self.cfg = cfg
        self.task = task
        self.cache = cache

    @property
    def enabled(self) -> bool:
        """Whether the proofreading pass can run: switched on and an LLM is configured."""
        return self.cfg.proofread and self.llm is not None

    @staticmethod
    def _cache_key(lang: str, context: dict[str, str], texts: list[str]) -> str:
        payload = json.dumps([lang, context, texts], ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    async def polish(
        self, video_id: str, cues: list[Cue], lang: str, context: dict[str, str]
    ) -> list[Cue]:
        if not cues:
            return cues
        cfg = self.cfg
        if not cfg.proofread:
            with events.stage(events.PROOFREAD, cues=len(cues)) as st:
                st.skip(reason="off")
            return cues
        if self.llm is None:
            with events.stage(events.PROOFREAD, cues=len(cues)) as st:
                st.skip(reason="no_llm", message="No [llm.captions] model is configured.")
            return cues
        with events.stage(events.PROOFREAD, cues=len(cues)) as st:
            st.set(
                batches=(len(cues) + cfg.proofread_batch - 1) // cfg.proofread_batch,
                language=lang,
            )
            out: list[Cue] = []
            corrected = warned = chars_in = chars_out = 0
            for i in range(0, len(cues), cfg.proofread_batch):
                part = cues[i : i + cfg.proofread_batch]
                texts = [" ".join(cue.lines) for cue in part]
                key = self._cache_key(lang, context, texts)
                fixed = self.cache.get(video_id, events.PROOFREAD, key) if self.cache else None
                if fixed is None:
                    try:
                        fixed = await self._polish_batch(texts, lang, context)
                    except Exception as exc:  # noqa: BLE001 - the job must survive an LLM failure
                        warned += 1
                        events.emit(
                            events.PROOFREAD_BATCH,
                            events.WARN,
                            batch=i // cfg.proofread_batch,
                            cues=len(part),
                            error_class=events.error_class(exc),
                            technical=events.technical(exc),
                        )
                        fixed = None
                    if fixed is not None and self.cache:
                        self.cache.put(video_id, events.PROOFREAD, key, fixed)
                else:
                    st.set(cached=True)
                if fixed is not None:
                    corrected += sum(1 for a, b in zip(texts, fixed, strict=True) if a != b)
                    chars_in += sum(len(text) for text in texts)
                    chars_out += sum(len(text) for text in fixed)
                else:
                    fixed = texts
                for cue, text in zip(part, fixed, strict=True):
                    lines = wrap_lines(text, cfg.max_chars_per_line, cfg.max_lines)
                    if lines is not None:
                        out.append(Cue(cue.start, cue.end, lines, cue.speaker))
                    else:
                        # the corrected text no longer fits one cue: re-split it over the cue's
                        # own span instead of storing lines that break the limits
                        out.extend(retime_split(text, cue.start, cue.end, cfg))
            st.set(corrected=corrected, warned=warned, chars_in=chars_in, chars_out=chars_out)
        return out

    async def _polish_batch(
        self, texts: list[str], lang: str, context: dict[str, str]
    ) -> list[str] | None:
        data = await self.llm.chat_json(
            self.task,
            [
                {"role": "system", "content": PROOFREAD_SYSTEM.format(lang=lang)},
                {
                    "role": "user",
                    "content": json.dumps({"video": context, "cues": texts}, ensure_ascii=False),
                },
            ],
        )
        if not isinstance(data, list) or len(data) != len(texts):
            return None
        fixed = [" ".join(str(item).split()) for item in data]
        if any(not text for text in fixed):
            return None
        total_in = sum(len(text) for text in texts)
        total_out = sum(len(text) for text in fixed)
        if total_out > total_in * self.cfg.proofread_max_ratio:
            return None  # sudden growth: invented content
        if total_out * self.cfg.proofread_max_ratio < total_in:
            return None  # sudden shrink: dropped content
        return fixed
