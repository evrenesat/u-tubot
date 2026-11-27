from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from .config import GLANCE_MAX_TOKENS, Config
from .db import Database
from .urlguard import Resolver, UrlRejected, guarded_get, system_resolver

log = logging.getLogger("utubot.prompts")

BUILTIN_SET_ID = "builtin"
DEFAULT_BUILTIN_KEY = "builtin/tldr"
DEFAULT_PANEL_KEY = "builtin/glance"
PANEL_ALIAS = "panel"
TASK_SUMMARY = "summary"
TASK_GLANCE = "glance"
TASK_CUTS = "cuts"
TASKS = (TASK_SUMMARY, TASK_GLANCE, TASK_CUTS)
# The user's own director's-cut presets live in this prompt set; only the phone's Cuts tab
# manages them (plan v2: saved presets are phone-only in v1).
CUT_SET_ID = "cut-presets"
CUT_SET_NAME = "My cuts"
MAX_CUT_PRESETS = 20
MAX_CUT_LABEL = 60
MIN_LENGTH_MIN, MAX_LENGTH_MIN = 0.5, 600.0
MIN_LENGTH_FRAC, MAX_LENGTH_FRAC = 0.05, 0.95
SET_FORMAT_VERSION = 1
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
TEMPLATE_VARS = (
    "title",
    "channel",
    "duration",
    "description",
    "transcript",
    "language",
    "question",
)
VAR_RE = re.compile(r"\{(" + "|".join(TEMPLATE_VARS) + r")\}")
MAX_PROMPTS_PER_SET = 50
MAX_TEXT_CHARS = 20000
MAX_TOKENS_LIMIT = 8000

DEFAULT_SYSTEM = (
    "You summarize YouTube videos for a viewer on a TV remote. Be concrete and faithful to the "
    "transcript, never invent details. Plain text, no preamble. Reply in {language}."
)


GLANCE_SYSTEM = (
    "You write the glance card a TV viewer sees beside a video while browsing. It must fit a "
    "small panel and be read in two seconds. Plain text only: no markdown, no preamble, never "
    "start with 'This video'. Be concrete and faithful to the transcript, never invent details. "
    "Reply in {language}."
)

CUT_SYSTEM = (
    "You build director's cuts of YouTube videos for a TV viewer: you choose which numbered "
    "transcript units to keep so the video plays the way the task asks. Reply ONLY with JSON: "
    '{"parts":[{"from":<int>,"to":<int>,"label":"<2-6 words>"}],'
    '"summary":"<one line, at most 120 characters>","kept_s":<int>}. '
    '"from" and "to" are the first and last unit id of one kept part. Ranges never overlap, ids '
    "must exist, and parts stay in video order. Be faithful to the transcript; never invent "
    "content and never add commentary."
)

STORY_READ_SYSTEM = (
    "You read a film or story from its numbered transcript units and build a story map. Lines "
    "starting with '---' (pauses, music) are not units and are never referred to. Reply ONLY with "
    'JSON: {"kind":"story|talk|other","language":"<code>","synopsis":"<at most 600 characters>",'
    '"cast":[{"id":"c1","name":"<main spelling>","aliases":["<other spellings>"],'
    '"role":"<at most 80 characters>"}],'
    '"scenes":[{"from":<unit id>,"to":<unit id>,"where":"<at most 40 characters>",'
    '"who":["c1"],"beats":[{"from":<unit id>,"to":<unit id>,"what":"<what happens, at most 160 '
    'characters>"}]}]}. '
    "Automatic captions have no speakers and spell names inconsistently: merge the spellings of "
    "one person into one cast entry. Scenes cover every unit you were asked to cover, in order, "
    "with no gap and no overlap; the beats of a scene cover that scene the same way. A beat is "
    "one event or exchange (usually 20 seconds to 3 minutes). Describe what happens and why it "
    "matters, in English, naming people by their cast name. Never invent events."
)

STORY_LINK_SYSTEM = (
    "You link the beats of a film or story by cause and effect. You get the synopsis, the cast and "
    "numbered beat cards, no transcript. Reply ONLY with JSON: "
    '{"threads":[{"id":"t1","title":"<at most 60 characters>","beats":[<beat ids>]}],'
    '"beats":[{"id":<beat id>,"kind":"setup|payoff|turn|reveal|gag|connective","weight":<1-5>,'
    '"needs":[<earlier beat ids>],"why":"<at most 100 characters>"}],"ending":[<beat ids>]}. '
    '"needs" lists the EARLIER beats a viewer would be lost without when this beat is shown '
    "but those beats are not: the plan or setup that explains a payoff, the scene that "
    "introduces a person or object it relies on, the decision behind a result (at most 4, only "
    "earlier ids). Be sparse: a viewer follows a story in order, so a beat that simply continues "
    "the previous beats needs nothing, and you never list the previous beat just because it "
    "comes before. About two beats in three have empty needs; a chain of beats each needing its "
    "neighbour is wrong. Every payoff and reveal needs at least one beat. "
    '"weight" is how much the beat matters to the story (5 = the story fails without it). '
    '"ending" lists the beats that make up the ending (the last resolution, never empty). '
    "Answer for every beat."
)

STORY_SELECT_SYSTEM = (
    "You choose which beats of a film stay in a shorter cut. You get the purpose, the synopsis, "
    "the threads and numbered beat cards with duration, kind, weight and the earlier beats each "
    "one needs. Reply ONLY with JSON: "
    '{"threads":[{"id":"t1","decision":"keep|compress|drop","reason":"<at most 100 characters>"}],'
    '"beats":[{"id":<beat id>,"keep":<0-3>}]}. '
    "keep: 3 = must stay, 2 = good, 1 = fine if there is room, 0 = drop. You score; you do not "
    "add up durations, the server builds the cut to the length and adds every beat a kept beat "
    "needs. Prefer dropping a whole thread to keeping only its ending. Answer for every beat."
)

STORY_CRITIC_SYSTEM = (
    "You are a strict viewer who has not seen the film. You get the purpose and the cut as the "
    "viewer gets it: the kept text in order, with a line '--- skipped m:ss ---' at each cut. "
    "Below the line '=== skipped beats ===' are the cards of the skipped beats, for naming fixes "
    "only. Reply ONLY with JSON: "
    '{"consistency":<0-10>,"density":<0-10>,"goal":<0-10>,'
    '"problems":[{"at_beat":<beat id>,"type":"missing_cause|unknown_person|dangling_setup|'
    'filler|abrupt|goal","note":"<at most 120 characters>","add":[<skipped beat ids>],'
    '"drop":[<kept beat ids>]}]}. '
    "consistency: can a first-time viewer follow every kept event; density: the share of kept "
    "time that carries story, character or a joke; goal: purpose and length. Name at most 8 "
    "problems, the worst first."
)

# The built-in director's-cut presets. The instruction is sent to the cut model as the task; a
# cut preset is never offered as a summary prompt (`PromptStore.describe` filters task=cut out).
PRETTY_CUT_LABELS = {
    "no-filler": "No filler",
    "answer": "Just the answer",
    "demo": "Only the demo",
    "highlights-5": "Highlights in 5 min",
    "skim-film": "Skim the film",
}
CUT_PRESET_INSTRUCTIONS = {
    "no-filler": (
        "Remove everything that is not the actual content of the video: intros, outros, channel "
        "plugs, 'like and subscribe' asks, sponsor segments and ads read aloud, dead air, "
        "repetition and small talk that adds nothing. Keep the substance from start to finish, "
        "in the original order."
    ),
    "skim-film": (
        "Skim the film: follow the story beat by beat and keep the best scenes, scene by scene, "
        "to about half the film's length. Keep the narrative arc and the strongest moments across "
        "the whole runtime, in order — the key turns, the revelations, the quiet beats that "
        "matter — not only the loudest highlights. Cut at scene and sentence boundaries, never "
        "mid-shot or mid-sentence; drop repeats, dead patches, filler and tangents that do not "
        "move the story forward."
    ),
    "answer": (
        "Keep only what directly answers what the title promises or asks — the reveal, the "
        "result, the conclusion, including the few sentences of setup the answer needs to make "
        "sense. Cut the long buildup, the tangents and everything after. If the video never "
        "answers it, keep the closest thing to an answer."
    ),
    "demo": (
        "Keep only the demonstration: the part where the thing itself is shown, used, tested, "
        "built or performed, step by step, from start to finish. Cut talk about it, the intro, "
        "the results discussion and everything else."
    ),
    "highlights-5": (
        "Keep the highlights: many short, distinct moments across the whole video — the payoff "
        "moments (demos, tests, results, reveals, conclusions) and the single most interesting, "
        "useful or entertaining scene or beat in each part of it, in the original order — not a "
        "few long blocks. Jump across the video: take the best small moments from the start, "
        "the middle and the end, each just a few seconds to a couple of minutes, as several "
        "separate parts. Skip intros, sponsor reads, like-and-subscribe asks, recaps, setup "
        "chatter and outros. Target about 5 minutes of kept time in total (between 4 and 6 "
        "minutes), made up of these short moments. Prefer concrete, dense passages over filler. "
        "This cut is fine however much it keeps, as long as it is the best of the video."
    ),
}


def cut_preset_prompt(name: str) -> Prompt:
    return Prompt(
        id=f"cut-{name}",
        label=PRETTY_CUT_LABELS[name],
        system="",
        template=CUT_PRESET_INSTRUCTIONS[name],
        max_tokens=2500,
        task=TASK_CUTS,
    )


GLANCE_TEMPLATE = (
    "Title: {title}\nChannel: {channel}\nDuration: {duration}\n"
    "Question the title poses (detected earlier, may be empty): {question}\n\n"
    "Transcript:\n{transcript}\n\n"
    "Write the glance card: at most 3 short lines and at most 280 characters in total.\n"
    "First decide whether the title (or thumbnail text, if the metadata gives any) poses or "
    'implies a question, or is a curiosity gap or clickbait: "you won\'t believe", "this '
    'changes everything", "the truth about", "why ...", "what happened", a number tease, '
    'a cliffhanger. If it is, line 1 is "→ " followed by the direct, specific answer from the '
    "transcript: the actual names, numbers or reveal, not a description of it. If the "
    'transcript does not answer it, line 1 is "→ " followed by a few words saying so, such as '
    '"Not answered in the video" (in {language}).\n'
    "Then 1 or 2 short lines with the gist.\n"
    "If the title asks nothing and teases nothing, skip the arrow line and give the gist in 2 "
    "or 3 short lines."
)
ANSWER_TITLE_TEMPLATE = (
    "Title: {title}\nChannel: {channel}\nDuration: {duration}\n"
    "Question the title poses (detected earlier, may be empty): {question}\n\n"
    "Transcript:\n{transcript}\n\n"
    "The title (or thumbnail text, if the metadata gives any) may pose or imply a question, or "
    'create curiosity or wonder: "you won\'t believe", "the truth about", "why ...", "what '
    'happened", a number tease, a cliffhanger. Find that first. Line 1: the question or '
    "curiosity gap, phrased as a short question. Then answer it directly in 2-3 sentences with "
    "the actual names, numbers or reveal, using only what the video says. If the video never "
    "answers it, say so. If the title asks nothing and teases nothing, give a 2 sentence summary "
    "instead."
)


class PromptError(ValueError):
    pass


class Prompt(BaseModel):
    id: str
    label: str
    default: bool = False
    system: str = ""
    template: str
    max_tokens: int = 700
    model: str | None = None
    task: str = TASK_SUMMARY
    # A saved cut preset's explicit length: minutes kept, or the fraction of the video kept.
    length_min: float | None = None
    length_frac: float | None = None

    @field_validator("length_min")
    @classmethod
    def _length_min(cls, v: float | None) -> float | None:
        if v is not None and not MIN_LENGTH_MIN <= v <= MAX_LENGTH_MIN:
            raise ValueError(f"length_min must be {MIN_LENGTH_MIN}..{MAX_LENGTH_MIN}")
        return v

    @field_validator("length_frac")
    @classmethod
    def _length_frac(cls, v: float | None) -> float | None:
        if v is not None and not MIN_LENGTH_FRAC <= v <= MAX_LENGTH_FRAC:
            raise ValueError(f"length_frac must be {MIN_LENGTH_FRAC}..{MAX_LENGTH_FRAC}")
        return v

    @model_validator(mode="after")
    def _one_length(self) -> Prompt:
        if self.length_min and self.length_frac:
            raise ValueError("give the length in minutes or as a fraction, not both")
        return self

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9._-]{1,64}")
        return v

    @field_validator("template")
    @classmethod
    def _template(cls, v: str) -> str:
        if not v.strip() or len(v) > MAX_TEXT_CHARS:
            raise ValueError("template empty or too long")
        return v

    @field_validator("system")
    @classmethod
    def _system(cls, v: str) -> str:
        if len(v) > MAX_TEXT_CHARS:
            raise ValueError("system too long")
        return v

    @field_validator("max_tokens")
    @classmethod
    def _max(cls, v: int) -> int:
        if not 16 <= v <= MAX_TOKENS_LIMIT:
            raise ValueError(f"max_tokens must be 16..{MAX_TOKENS_LIMIT}")
        return v

    @field_validator("task")
    @classmethod
    def _task(cls, v: str) -> str:
        if v not in TASKS:
            raise ValueError(f"task must be one of {', '.join(TASKS)}")
        return v

    def content_hash(self) -> str:
        parts: list[Any] = [self.system, self.template, self.max_tokens, self.model]
        if self.task != TASK_SUMMARY:
            parts.append(self.task)
        if self.length_min or self.length_frac:
            parts.append([self.length_min, self.length_frac])
        blob = json.dumps(parts, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()


class PromptSet(BaseModel):
    tubeai_prompt_set: int
    id: str
    name: str
    version: str = ""
    prompts: list[Prompt] = Field(default_factory=list)

    @field_validator("tubeai_prompt_set")
    @classmethod
    def _fmt(cls, v: int) -> int:
        if v != SET_FORMAT_VERSION:
            raise ValueError(f"unsupported tubeai_prompt_set version {v}")
        return v

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("id must match [A-Za-z0-9._-]{1,64}")
        return v

    @field_validator("prompts")
    @classmethod
    def _prompts(cls, v: list[Prompt]) -> list[Prompt]:
        if not v:
            raise ValueError("a set needs at least one prompt")
        if len(v) > MAX_PROMPTS_PER_SET:
            raise ValueError("too many prompts")
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate prompt ids")
        return v


def validate_prompt_set(data: Any) -> PromptSet:
    if not isinstance(data, dict):
        raise PromptError("prompt set must be a JSON object")
    try:
        return PromptSet.model_validate(data)
    except ValidationError as exc:
        parts = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise PromptError("; ".join(parts)) from exc


def render(text: str, values: dict[str, str]) -> str:
    return VAR_RE.sub(lambda m: values.get(m.group(1), ""), text)


BUILTIN_SET = PromptSet(
    tubeai_prompt_set=SET_FORMAT_VERSION,
    id=BUILTIN_SET_ID,
    name="Built-in",
    version="2",
    prompts=[
        Prompt(
            id="glance",
            label="Glance",
            system=GLANCE_SYSTEM,
            template=GLANCE_TEMPLATE,
            max_tokens=GLANCE_MAX_TOKENS,
            task=TASK_GLANCE,
        ),
        Prompt(
            id="tldr",
            label="TL;DR",
            default=True,
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\n"
                "Transcript:\n{transcript}\n\n"
                "Give a TL;DR as 5 short bullet points (start each with '- '). Lead with the "
                "single most important takeaway. Max 900 characters total."
            ),
            max_tokens=700,
        ),
        Prompt(
            id="answer-title",
            label="Answer the title",
            system=DEFAULT_SYSTEM,
            template=ANSWER_TITLE_TEMPLATE,
            max_tokens=400,
        ),
        Prompt(
            id="takeaways",
            label="Key takeaways + timestamps",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nDuration: {duration}\n\nTranscript (with [mm:ss] markers):\n"
                "{transcript}\n\n"
                "List the 5-8 key takeaways, each on its own line formatted as "
                "'[mm:ss] takeaway' using the nearest timestamp from the transcript. "
                "Keep each under 110 characters."
            ),
            max_tokens=900,
        ),
        Prompt(
            id="worth-it",
            label="Is it worth watching?",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\nDuration: {duration}\n\n"
                "Transcript:\n{transcript}\n\n"
                "Decide if this video is worth the viewer's time. Start with 'Verdict: Watch', "
                "'Verdict: Skim' or 'Verdict: Skip'. Then give 3 short reasons, say roughly how "
                "much of the runtime is real substance versus filler, and name the best part's "
                "timestamp if there is one. Max 700 characters."
            ),
            max_tokens=600,
        ),
        Prompt(
            id="eli-new",
            label="Explain like I'm new",
            system=DEFAULT_SYSTEM,
            template=(
                "Title: {title}\nChannel: {channel}\n\nTranscript:\n{transcript}\n\n"
                "Explain what this video covers for someone with no background. Define any "
                "jargon in plain words, use one everyday analogy, and finish with one sentence "
                "on why it matters. Max 1000 characters."
            ),
            max_tokens=700,
        ),
        cut_preset_prompt("no-filler"),
        cut_preset_prompt("answer"),
        cut_preset_prompt("demo"),
        cut_preset_prompt("highlights-5"),
        cut_preset_prompt("skim-film"),
    ],
)


class PromptStore:
    def __init__(
        self,
        cfg: Config,
        db: Database,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ):
        self.cfg, self.db = cfg, db
        self._transport = transport
        self._resolver = resolver

    def get_set(self, user: str, set_id: str) -> tuple[PromptSet, str | None] | None:
        if set_id == BUILTIN_SET_ID:
            return BUILTIN_SET, None
        row = self.db.one(
            "SELECT json, source_url FROM prompt_sets WHERE user=? AND set_id=?", [user, set_id]
        )
        if not row:
            return None
        return PromptSet.model_validate_json(row["json"]), row["source_url"]

    def list_sets(self, user: str) -> list[tuple[PromptSet, str | None]]:
        out: list[tuple[PromptSet, str | None]] = [(BUILTIN_SET, None)]
        rows = self.db.all(
            "SELECT json, source_url FROM prompt_sets WHERE user=? ORDER BY set_id", [user]
        )
        out.extend((PromptSet.model_validate_json(r["json"]), r["source_url"]) for r in rows)
        return out

    def default_key(self, user: str) -> str:
        row = self.db.one("SELECT prompt_key FROM user_default WHERE user=?", [user])
        if row and self.resolve(user, row["prompt_key"]):
            return row["prompt_key"]
        return DEFAULT_BUILTIN_KEY

    def panel_key(self, user: str) -> str:
        row = self.db.one("SELECT prompt_key FROM user_panel_default WHERE user=?", [user])
        for key in (row["prompt_key"] if row else None, self.cfg.summary.panel_prompt):
            if key and self.resolve(user, key):
                return key
        return DEFAULT_PANEL_KEY

    def resolve(self, user: str, key: str) -> Prompt | None:
        set_id, _, prompt_id = key.partition("/")
        found = self.get_set(user, set_id)
        if not found:
            return None
        return next((p for p in found[0].prompts if p.id == prompt_id), None)

    def save_set(
        self,
        user: str,
        pset: PromptSet,
        source_url: str | None = None,
        *,
        from_cut_store: bool = False,
    ) -> None:
        if pset.id == BUILTIN_SET_ID:
            raise PromptError("the builtin set cannot be replaced")
        if pset.id == CUT_SET_ID and not from_cut_store:
            raise PromptError("the cut-presets set is managed by the cut sheet, not imported here")
        self.db.execute(
            "INSERT OR REPLACE INTO prompt_sets(user,set_id,json,source_url,updated_at)"
            " VALUES(?,?,?,?,?)",
            [user, pset.id, pset.model_dump_json(), source_url, time.time()],
        )

    def delete_set(self, user: str, set_id: str) -> bool:
        if set_id == BUILTIN_SET_ID:
            raise PromptError("the builtin set cannot be deleted")
        found = self.get_set(user, set_id)
        if not found:
            return False
        self.db.execute("DELETE FROM prompt_sets WHERE user=? AND set_id=?", [user, set_id])
        for table in ("user_default", "user_panel_default"):
            row = self.db.one(f"SELECT prompt_key FROM {table} WHERE user=?", [user])
            if row and row["prompt_key"].startswith(f"{set_id}/"):
                self.db.execute(f"DELETE FROM {table} WHERE user=?", [user])
        return True

    def set_default(self, user: str, key: str) -> None:
        prompt = self.resolve(user, key)
        if prompt is None:
            raise PromptError(f"unknown prompt {key}")
        if prompt.task == TASK_CUTS:
            raise PromptError("a director's cut preset cannot be a summary default")
        self.db.execute(
            "INSERT OR REPLACE INTO user_default(user,prompt_key) VALUES(?,?)", [user, key]
        )

    def set_panel_default(self, user: str, key: str) -> None:
        prompt = self.resolve(user, key)
        if prompt is None:
            raise PromptError(f"unknown prompt {key}")
        if prompt.task == TASK_CUTS:
            raise PromptError("a director's cut preset cannot be the panel prompt")
        self.db.execute(
            "INSERT OR REPLACE INTO user_panel_default(user,prompt_key) VALUES(?,?)", [user, key]
        )

    def clear_default(self, user: str) -> None:
        self.db.execute("DELETE FROM user_default WHERE user=?", [user])

    def clear_panel_default(self, user: str) -> None:
        self.db.execute("DELETE FROM user_panel_default WHERE user=?", [user])

    def server_panel_key(self) -> str:
        """The panel prompt when the user chose none: `[summary] panel_prompt`, else the built-in glance."""
        return self.cfg.summary.panel_prompt or DEFAULT_PANEL_KEY

    def has_override(self, user: str) -> dict[str, bool]:
        return {
            "default": self.db.one("SELECT 1 FROM user_default WHERE user=?", [user]) is not None,
            "panel_default": self.db.one("SELECT 1 FROM user_panel_default WHERE user=?", [user])
            is not None,
        }

    async def fetch(self, url: str) -> PromptSet:
        limit = self.cfg.summary.max_import_bytes
        body = bytearray()
        try:
            async with guarded_get(
                url,
                allow_hosts=self.cfg.summary.import_allow_hosts,
                max_redirects=self.cfg.summary.import_max_redirects,
                timeout_s=self.cfg.summary.import_timeout_s,
                transport=self._transport,
                resolver=self._resolver,
            ) as resp:
                if resp.status_code >= 400:
                    raise PromptError(f"fetch failed: http {resp.status_code}")
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise PromptError(f"prompt set exceeds {limit} bytes")
        except UrlRejected as exc:
            raise PromptError(f"url not allowed: {exc}") from exc
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("prompt import fetch failed: %s", type(exc).__name__)
            raise PromptError("fetch failed") from exc
        try:
            data = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PromptError("not valid JSON") from exc
        return validate_prompt_set(data)

    async def import_url(self, user: str, url: str) -> PromptSet:
        pset = await self.fetch(url)
        self.save_set(user, pset, source_url=url)
        return pset

    async def refresh_all(self, user: str) -> dict[str, str]:
        rows = self.db.all(
            "SELECT set_id, source_url FROM prompt_sets WHERE user=? AND source_url IS NOT NULL",
            [user],
        )
        report: dict[str, str] = {}
        for row in rows:
            try:
                pset = await self.fetch(row["source_url"])
                if pset.id != row["set_id"]:
                    self.db.execute(
                        "DELETE FROM prompt_sets WHERE user=? AND set_id=?", [user, row["set_id"]]
                    )
                self.save_set(user, pset, source_url=row["source_url"])
                report[pset.id] = "ok"
            except PromptError as exc:
                report[row["set_id"]] = f"error: {exc}"
        return report

    def describe(self, user: str) -> dict[str, Any]:
        default = self.default_key(user)
        panel = self.panel_key(user)
        sets = []
        for pset, source_url in self.list_sets(user):
            shown = [
                {
                    "id": p.id,
                    "key": f"{pset.id}/{p.id}",
                    "label": p.label,
                    "default": f"{pset.id}/{p.id}" == default,
                    "panel_default": f"{pset.id}/{p.id}" == panel,
                }
                for p in pset.prompts
                if p.task != TASK_CUTS
            ]
            # A set that only holds cut presets belongs to the Cuts tab (phone-only), never to
            # the summary prompt pickers.
            if not shown:
                continue
            sets.append(
                {
                    "id": pset.id,
                    "name": pset.name,
                    "version": pset.version,
                    "source_url": source_url,
                    "prompts": shown,
                }
            )
        return {"default": default, "panel_default": panel, "sets": sets}

    def cut_prompts(self, user: str) -> list[Prompt]:
        """Every director's-cut preset the user can pick: the built-ins plus their own sets.

        A user set wins over the built-in of the same id, so an owner can tune a preset.
        """
        out: dict[str, Prompt] = {p.id: p for p in BUILTIN_SET.prompts if p.task == TASK_CUTS}
        for pset, _url in reversed(self.list_sets(user)):
            if pset.id == BUILTIN_SET_ID:
                continue
            for p in pset.prompts:
                if p.task == TASK_CUTS:
                    out[p.id] = p
        return list(out.values())

    def own_cut_presets(self, user: str) -> list[Prompt]:
        """The presets this user saved on the phone, in the order they were saved."""
        found = self.get_set(user, CUT_SET_ID)
        if not found:
            return []
        return [p for p in found[0].prompts if p.task == TASK_CUTS]

    def save_cut_preset(
        self,
        user: str,
        label: str,
        prompt: str,
        length_min: float | None = None,
        length_frac: float | None = None,
    ) -> Prompt:
        """Save a description as the user's own cut preset. The same label and description
        replace the earlier copy instead of piling duplicates."""
        label = (label or "").strip()
        prompt = (prompt or "").strip()
        if not label:
            raise PromptError("a saved preset needs a name")
        if len(label) > MAX_CUT_LABEL:
            raise PromptError(f"the preset name is longer than {MAX_CUT_LABEL} characters")
        if not prompt:
            raise PromptError("a saved preset needs the description of the cut")
        if len(prompt) > MAX_TEXT_CHARS:
            raise PromptError(f"the description is longer than {MAX_TEXT_CHARS} characters")
        if length_min and length_frac:
            raise PromptError("give the length in minutes or as a fraction, not both")
        try:
            made = self._cut_prompt(label, prompt, length_min, length_frac)
        except ValidationError as exc:
            raise PromptError(exc.errors()[0]["msg"].removeprefix("Value error, ")) from exc
        own = self.own_cut_presets(user)
        if not any(p.id == made.id for p in own) and len(own) >= MAX_CUT_PRESETS:
            raise PromptError(f"at most {MAX_CUT_PRESETS} saved presets; delete one first")
        prompts = [p for p in own if p.id != made.id]
        prompts.append(made)
        pset = PromptSet(
            tubeai_prompt_set=SET_FORMAT_VERSION,
            id=CUT_SET_ID,
            name=CUT_SET_NAME,
            version=str(len(prompts)),
            prompts=prompts,
        )
        self.save_set(user, pset, from_cut_store=True)
        return made

    @staticmethod
    def _cut_prompt(
        label: str, prompt: str, length_min: float | None, length_frac: float | None
    ) -> Prompt:
        return Prompt(
            id="cut-mine-" + hashlib.sha256((label + "\0" + prompt).encode()).hexdigest()[:12],
            label=label,
            system="",
            template=prompt,
            max_tokens=2500,
            task=TASK_CUTS,
            length_min=length_min or None,
            length_frac=length_frac or None,
        )

    def delete_cut_preset(self, user: str, prompt_id: str) -> bool:
        """Remove one saved preset; the last one deletes the set."""
        own = [p for p in self.own_cut_presets(user) if p.id != prompt_id]
        if len(own) == len(self.own_cut_presets(user)):
            return False
        if not own:
            self.db.execute("DELETE FROM prompt_sets WHERE user=? AND set_id=?", [user, CUT_SET_ID])
            return True
        pset = PromptSet(
            tubeai_prompt_set=SET_FORMAT_VERSION,
            id=CUT_SET_ID,
            name=CUT_SET_NAME,
            version=str(len(own)),
            prompts=own,
        )
        self.save_set(user, pset, from_cut_store=True)
        return True
