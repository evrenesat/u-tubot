"""The offline test set for director's cuts and the scorer behind `scripts/cut_bench.py`.

Five hand-written transcripts (caption-like fragments, invented content, no real video) with
three or four requests each (16 requests), and hand-marked must-keep / must-skip time ranges. The scorer runs the
real cut engine over a fixture (`build_units` -> the model -> `parse_cut_answer` ->
`finalize_parts`) and measures how much of the must-keep time the finished cut kept and how
much must-skip time leaked in. No network here: the model is a callable the caller supplies.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import CutsConfig, LLMTask
from .cuts import (
    CUT_JSON_RULES,
    CUT_SYSTEM,
    CutEngine,
    CutFormatError,
    CutRefused,
    Part,
    Unit,
    build_units,
    effective_target_s,
    finalize_parts,
    keep_guards,
    parse_chapters,
    parse_cut_answer,
    select_for_target,
    serialize_units,
    target_band,
)
from .llm import LLMError, extract_json
from .prompts import BUILTIN_SET, TASK_CUTS


def preset_instruction(preset_id: str) -> str:
    """The instruction a builtin preset stands for (the bench marks spans against it)."""
    prompt = next(
        (p for p in BUILTIN_SET.prompts if p.task == TASK_CUTS and p.id == preset_id), None
    )
    if prompt is None:
        raise KeyError(preset_id)
    return prompt.template


@dataclass
class BenchRequest:
    """One request against one transcript: the instruction plus the hand-marked spans.

    `budget_s` caps how much the cut may keep before the score is diluted: a cut that answers
    "just the answer" but keeps half the video is a bad cut even when nothing marked leaked.
    `None` means no budget (the default: one and a half times the marked keep time)."""

    name: str
    instruction: str
    preset_id: str | None
    keep: list[tuple[float, float]]
    skip: list[tuple[float, float]]
    budget_s: float | None = None
    target_s: int | None = None  # kept length the request asks for; overrides the preset's


@dataclass
class BenchTranscript:
    """One fixture transcript: caption-like segments plus the video facts."""

    id: str
    title: str
    channel: str
    duration_s: float
    description: str
    segments: list[tuple[float, float, str]]
    requests: list[BenchRequest] = field(default_factory=list)
    cuts_overrides: dict[str, Any] = field(default_factory=dict)  # `[cuts]` values for this fixture


# ---- the fixture builder ----------------------------------------------------------------------


def _cap(
    lines: list[str], *, start: float, gap: float = 0.35
) -> tuple[list[tuple[float, float, str]], float]:
    """Caption-like fragments for one block: speaking-pace lines, a short pause after each.

    Returns the segments and the time the block ends at (the next block starts later)."""
    segs: list[tuple[float, float, str]] = []
    t = start
    for line in lines:
        dur = max(1.8, round(0.46 * len(line.split()), 2))
        segs.append((round(t, 2), round(t + dur, 2), line))
        t += dur + gap
    return segs, round(t - gap, 2)


class _Layout:
    """Blocks with names, so a fixture marks its spans against the real layout instead of
    hardcoding seconds: `layout.span("intro")` or `layout.span("mesh_test", "verdict")`."""

    def __init__(self, named: dict[str, list[str]], pause: float = 1.4):
        self.spans: dict[str, tuple[float, float]] = {}
        segs: list[tuple[float, float, str]] = []
        at = 0.0
        names = list(named)
        for i, name in enumerate(names):
            block, end = _cap(named[name], start=at)
            segs.extend(block)
            self.spans[name] = (block[0][0], end)
            at = end + (pause if i < len(names) - 1 else 0.0)
        self.segments = segs
        self.duration_s = round(segs[-1][1] + 0.8, 2)

    def span(self, *names: str) -> list[tuple[float, float]]:
        return [self.spans[name] for name in names]


def _make(
    transcript_id: str,
    title: str,
    channel: str,
    description: str,
    layout: _Layout,
    requests: list[BenchRequest],
) -> BenchTranscript:
    return BenchTranscript(
        id=transcript_id,
        title=title,
        channel=channel,
        duration_s=layout.duration_s,
        description=description,
        segments=layout.segments,
        requests=requests,
    )


# ---- the fixtures (invented content, hand-marked) ----------------------------------------------


def _fixture_router() -> BenchTranscript:
    lay = _Layout(
        {
            "intro": [
                "Welcome back to the channel.",
                "Today we finally look at the new firmware for the XR-9 routers.",
                "Before we start, a quick reminder that the newsletter is free.",
                "Also the merch store link is somewhere below, I think.",
            ],
            "sponsor": [
                "This video is sponsored by NordShield VPN.",
                "NordShield runs on routers, phones, laptops, even that old tablet.",
                "One account covers the whole family and the kill switch is solid.",
                "Use code TECHNOTES at checkout for sixty-three percent off.",
                "Right, back to the firmware.",
            ],
            "what_changed": [
                "So the big change is that channels are scheduled per device.",
                "Your phone gets the fast band, the doorbell stays on the slow one.",
                "That used to be a per-router setting, which made no sense at all.",
                "Second, the mesh handoff code was rewritten.",
                "Roaming between nodes used to drop VoIP calls mid-sentence.",
                "Now the client keeps its stream while it hops between nodes.",
                "Third, WPA3 transition mode finally works with old smart plugs.",
                "And the update ships patched CVEs from the last eight months.",
                "Four of them were exploitable from the guest network.",
            ],
            "the_catch": [
                "One real downside to know about.",
                "Rollback is only possible for thirty days after the update.",
                "After that the old image is gone from the slot.",
            ],
            "mesh_test": [
                "I set up three nodes across two floors for the roaming test.",
                "I walked from the kitchen to the office on a video call.",
                "The old firmware dropped the call at the stairwell every time.",
                "With the new firmware the call survived with one short blip.",
                "Latency during the hop peaked at one hundred ten milliseconds.",
                "Then it settled back under twenty, which is what you want.",
            ],
            "verdict": [
                "So, should you update the XR-9?",
                "Yes, update it today, and reboot every mesh node together.",
                "That one reboot order is what makes the roaming fix stick.",
            ],
            "outro": [
                "That is it for this one.",
                "Patreon supporters get the raw latency spreadsheet every month.",
                "Links to everything are in the description below.",
                "Thanks for watching, and see you in the next video.",
            ],
        }
    )
    return _make(
        "bench-router",
        "XR-9 router firmware: what actually changes",
        "Tech Notes",
        "XR-9 firmware deep dive.\n00:00 Intro\nMesh roaming test\nVerdict\n",
        lay,
        [
            BenchRequest(
                name="no-filler",
                instruction=preset_instruction("cut-no-filler"),
                preset_id="cut-no-filler",
                keep=lay.span("what_changed", "the_catch", "mesh_test", "verdict"),
                skip=lay.span("intro", "sponsor", "outro"),
            ),
            BenchRequest(
                name="just-the-answer",
                instruction=preset_instruction("cut-answer"),
                preset_id="cut-answer",
                keep=lay.span("verdict"),
                skip=lay.span("intro", "sponsor", "outro"),
            ),
            BenchRequest(
                name="mesh-roaming-test",
                instruction="Only the part where he tests how the mesh handles roaming between rooms.",
                preset_id=None,
                keep=lay.span("mesh_test"),
                skip=lay.span("intro", "sponsor", "outro"),
            ),
            BenchRequest(
                name="highlights-1min",
                instruction="Keep the highlights: the most useful minute of the video.",
                preset_id=None,
                keep=lay.span("what_changed", "the_catch", "mesh_test", "verdict"),
                skip=lay.span("intro", "sponsor", "outro"),
                budget_s=75.0,
                target_s=60,
            ),
        ],
    )


def _fixture_sourdough() -> BenchTranscript:
    lay = _Layout(
        {
            "intro": [
                "Real sourdough with twenty minutes of work a day.",
                "That is the promise today and we will keep it.",
                "Smash the like button if you have killed a starter before.",
            ],
            "gear_list": [
                "You need a banneton, or a bowl and a tea towel.",
                "A razor or very sharp blade for scoring.",
                "A Dutch oven, any heavy pot with a lid works.",
                "A digital scale, volume measures do not work for flour.",
                "That is the whole list, nothing else.",
            ],
            "folds": [
                "We do four sets of stretches and folds in the first two hours.",
                "Wet your hand, grab the dough from one side and pull it up.",
                "Fold it over the top and turn the bowl a quarter.",
                "Repeat that on the other three sides and rest thirty minutes.",
                "By set four the dough holds together and springs back slowly.",
                "Do not tear it; gentler folds keep the gas in.",
            ],
            "shape_retard": [
                "Shape with one confident pass, seam down into the floured basket.",
                "Then it goes into the fridge overnight, twelve to sixteen hours.",
                "The cold retard is what builds the tang you are after.",
            ],
            "baking": [
                "Bake in a fully preheated Dutch oven at two-thirty Celsius.",
                "Twenty minutes covered, then lid off for twenty more.",
                "Steam is the whole trick behind the blistered crust.",
                "Let it cool one full hour or the crumb turns gummy.",
            ],
            "mistakes": [
                "Three mistakes cause almost every sad loaf I see.",
                "Under-fermented dough, sliced too warm, and a weak bake.",
                "If the crumb is dense the bulk was short, not the flour.",
                "If the crust is pale your oven lied about its temperature.",
                "Buy a cheap oven thermometer and stop guessing.",
            ],
            "schedule": [
                "Here is the whole schedule in one minute.",
                "Feed the starter at eight in the morning.",
                "Mix at noon, folds at one, two, three and four.",
                "Shape at six, fridge overnight, bake the next afternoon.",
                "Twenty minutes of hands-on time, that is the whole deal.",
            ],
            "outro": [
                "If this helped, the playlist has the rye version.",
                "Comment what you struggle with and I will cover it.",
                "Thanks for baking along with me today.",
            ],
        }
    )
    return _make(
        "bench-sourdough",
        "Sourdough with 20 minutes of work a day - the full schedule",
        "Rise & Crumb",
        "The busy-person sourdough method.\n00:00 Intro\nThe folds\nThe schedule\n",
        lay,
        [
            BenchRequest(
                name="no-filler",
                instruction=preset_instruction("cut-no-filler"),
                preset_id="cut-no-filler",
                keep=lay.span("folds", "shape_retard", "baking", "mistakes"),
                skip=lay.span("intro", "gear_list", "outro"),
            ),
            BenchRequest(
                name="just-the-answer",
                instruction=preset_instruction("cut-answer"),
                preset_id="cut-answer",
                keep=lay.span("schedule"),
                skip=lay.span("intro", "gear_list", "outro"),
            ),
            BenchRequest(
                name="only-the-folds",
                instruction="Only the stretching and folding steps, nothing else.",
                preset_id=None,
                keep=lay.span("folds"),
                skip=lay.span("intro", "gear_list", "outro"),
            ),
        ],
    )


def _fixture_sleep() -> BenchTranscript:
    lay = _Layout(
        {
            "hook": [
                "If you keep waking at exactly three in the morning, stay here.",
                "This is not about coffee, well, mostly not about coffee.",
            ],
            "sponsor_one": [
                "A quick word from the sponsor of today's episode.",
                "AuraRest makes the sleep tracker I wear in every video.",
                "It scores your nights without a subscription, which is rare.",
                "Code SLEEPLAB takes twenty percent off the starter kit.",
                "Now, the science.",
            ],
            "mechanism": [
                "Sleep runs in ninety minute cycles of light, deep and REM.",
                "Cortisol, the wake-up hormone, starts rising around four.",
                "If your blood sugar dipped at two, cortisol arrives early.",
                "That early peak drags you out of REM and you feel wide awake.",
                "Alcohol makes the dip worse, which is the three a.m. trap.",
                "In one line: your body ran out of fuel before morning.",
            ],
            "causes": [
                "Three causes show up again and again in the clinic.",
                "A late heavy dinner that spikes then crashes glucose.",
                "A bedroom that warms past twenty-one degrees by morning.",
                "And unhandled rumination, the brain rehearsing tomorrow.",
                "Each one alone can do it; two together almost always do.",
            ],
            "sponsor_two": [
                "One more quick thanks to AuraRest for supporting the channel.",
                "If you order with the code, mention it in the comments.",
                "Back to what actually helps.",
            ],
            "fixes": [
                "Fix one: a spoon of peanut butter before bed levels the dip.",
                "Fix two: set the thermostat to drop, not rise, overnight.",
                "Fix three: write tomorrow's list before dinner, not in bed.",
                "Give each fix five nights before you judge it.",
                "If you still wake, get up, dim light, boring book, back in.",
            ],
            "outro": [
                "That is the whole picture in eleven minutes.",
                "The references are in the description, real journals only.",
                "Subscribe if this was useful, sleep well tonight.",
            ],
        }
    )
    return _make(
        "bench-sleep",
        "Why you wake up at 3 a.m. - and the fix",
        "Sleep Lab",
        "The 3 a.m. waking explained.\n00:00 The hook\nThe fixes\n",
        lay,
        [
            BenchRequest(
                name="no-filler",
                instruction=preset_instruction("cut-no-filler"),
                preset_id="cut-no-filler",
                # the hook is unmarked either way: a cut may keep or drop it
                keep=lay.span("mechanism", "causes", "fixes"),
                skip=lay.span("sponsor_one", "sponsor_two", "outro"),
            ),
            BenchRequest(
                name="just-the-answer",
                instruction=preset_instruction("cut-answer"),
                preset_id="cut-answer",
                keep=lay.span("fixes"),
                skip=lay.span("sponsor_one", "sponsor_two", "outro"),
            ),
            BenchRequest(
                name="only-the-fixes",
                instruction="Only the practical fixes, skip everything else.",
                preset_id=None,
                keep=lay.span("fixes"),
                skip=lay.span("sponsor_one", "sponsor_two", "outro"),
            ),
        ],
    )


def _fixture_charger() -> BenchTranscript:
    lay = _Layout(
        {
            "intro": [
                "The EU common charger rule is in force now.",
                "Twenty minutes, no jargon, just what it means for you.",
            ],
            "the_rule": [
                "From December twenty-eight, most new devices ship USB-C.",
                "That covers phones, tablets, cameras, headphones and handhelds.",
                "Laptops have until spring twenty-eight to comply.",
                "The rule is about the port, not the cable you already own.",
                "Your old chargers keep working; nothing is being banned.",
                "Fast charging claims must now be provable on the label.",
            ],
            "recap_one": [
                "So to recap: one charger for everything.",
                "USB-C becomes the port, laptops get a longer runway.",
                "Keep that in mind while we go through the details.",
            ],
            "laptops": [
                "For laptops the change is bigger than people expect.",
                "Charging over USB-C becomes the required default path.",
                "Any laptop sold in the EU must charge from a USB-C PD port.",
                "Proprietary barrels can remain as an optional extra port.",
                "Minimum power delivery is one hundred watts for laptops.",
                "That is why new docks now advertise one-forty and beyond.",
            ],
            "sponsor": [
                "This channel is supported by VoltCables.",
                "Their braided USB-C cables survived my torture bench.",
                "VoltCables dot com has the certified one-forty watt set.",
                "Use PLAIN ten for the bundle.",
            ],
            "recap_two": [
                "So, again, from the top: one charger, one port.",
                "Phones now, laptops by twenty-eight, no bans, no panic.",
                "Let me finish with the dates.",
            ],
            "dates": [
                "Devices sold before the deadline stay on sale, no retrofit.",
                "Radio gear, some medical devices, and embedded systems are exempt.",
                "Wireless charging pads are untouched by this rule.",
                "Enforcement starts with market checks, not recalls.",
            ],
            "qa": [
                "Quick questions from the comments now.",
                "Does this apply to the UK? No, but brands standardise anyway.",
                "Will prices rise? Cables cost less than proprietary bricks.",
                "What about e-bikes? Larger batteries are outside scope.",
            ],
            "outro": [
                "That is the whole rule in plain language.",
                "The commission page is linked below if you like reading law.",
                "See you in the next one.",
            ],
        }
    )
    return _make(
        "bench-charger",
        "The EU common charger rule, explained",
        "Plain Policy",
        "USB-C rule explained.\n00:00 Intro\nThe rule\nDates\n",
        lay,
        [
            BenchRequest(
                name="no-filler",
                instruction=preset_instruction("cut-no-filler"),
                preset_id="cut-no-filler",
                # the Q&A is unmarked: a cut may keep or drop it
                keep=lay.span("the_rule", "laptops", "dates"),
                skip=lay.span("intro", "recap_one", "recap_two", "sponsor", "outro"),
            ),
            BenchRequest(
                name="laptop-buyers",
                instruction="Only what changes for laptop buyers.",
                preset_id=None,
                keep=lay.span("laptops"),
                skip=lay.span("intro", "recap_one", "recap_two", "sponsor", "outro"),
            ),
            BenchRequest(
                name="no-recaps",
                instruction="Cut out every recap and the sponsor; keep the facts.",
                preset_id=None,
                keep=lay.span("the_rule", "laptops", "dates"),
                skip=lay.span("intro", "recap_one", "recap_two", "sponsor", "outro"),
            ),
        ],
    )


def _fixture_projector() -> BenchTranscript:
    lay = _Layout(
        {
            "unboxing": [
                "The box arrived in a box, which is very on brand.",
                "Cables, remote, a lens cloth, the usual padding.",
                "Two hundred euros is the claim to beat here.",
                "Let me get it out of the plastic first.",
                "It is lighter than it looks, that is promising.",
                "The remote feels like 2009, but it works.",
                "Okay, plastic off, first power on.",
            ],
            "sponsor": [
                "Before the tests, a word from GlowShelf lighting.",
                "Bias lighting makes any projector look twice as good.",
                "GlowShelf kits are USB powered and stick on with tape.",
                "Code PROJECTOR saves you fifteen percent this week.",
            ],
            "setup_struggle": [
                "Setup was not one button, let me be honest.",
                "Keystone took four attempts to square up.",
                "The fan is audible in quiet scenes, remember that.",
                "Focus ring is stiff but holds its position.",
            ],
            "dark_test": [
                "Now the test you came for, full dark, blackout curtains.",
                "The image fills a one hundred twenty inch wall.",
                "Color out of the box is actually close to accurate.",
                "Contrast is where the money shows; blacks are grey-ish.",
                "Motion at twenty-four frames judders on pans.",
                "Text is readable at this size, barely, at the edges.",
                "For films in the dark, this is genuinely watchable.",
                "For work, the edges smear and you will notice.",
            ],
            "daylight_test": [
                "Daylight test, curtains open, midday sun.",
                "The image washes out to almost nothing at two meters.",
                "With the blinds half closed it fights back.",
                "You can watch sport like this; you cannot read slides.",
            ],
            "verdict": [
                "So should you buy the LumaBeam C2?",
                "For movie nights in a dark room, yes, with the lights off.",
                "For daytime or work, no; save for something brighter.",
                "At two hundred euros the dark-room value is real.",
            ],
            "outro": [
                "Full measurements are on the blog, link below.",
                "Next week: the ceiling mount that actually works.",
                "Thanks for watching to the end, it helps a lot.",
            ],
        }
    )
    return _make(
        "bench-projector",
        "I tried the cheapest 4K projector so you don't have to",
        "Tech Notes",
        "Budget projector week.\n00:00 Unboxing\nDark room test\nVerdict\n",
        lay,
        [
            BenchRequest(
                name="no-filler",
                instruction=preset_instruction("cut-no-filler"),
                preset_id="cut-no-filler",
                # the setup struggle is unmarked: filler-adjacent, a cut may keep or drop it
                keep=lay.span("dark_test", "daylight_test", "verdict"),
                skip=lay.span("unboxing", "sponsor", "outro"),
            ),
            BenchRequest(
                name="just-the-answer",
                instruction=preset_instruction("cut-answer"),
                preset_id="cut-answer",
                keep=lay.span("verdict"),
                skip=lay.span("unboxing", "sponsor", "outro"),
            ),
            BenchRequest(
                name="only-the-dark-test",
                instruction="Only the part where he actually projects it in a dark room.",
                preset_id=None,
                keep=lay.span("dark_test"),
                skip=lay.span("unboxing", "sponsor", "outro"),
            ),
        ],
    )


LONG_SECTION_LINES = 110
LONG_FILLER_SECTIONS = 13
LONG_KEY_LINES = 110
LONG_EDGE_LINES = 60
LONG_CHUNK_TOKENS = 6000
LONG_MAX_INPUT_TOKENS = 12000


def _fixture_long() -> BenchTranscript:
    """A three-hour talk generated from templates: filler sections, two short key sections
    ("decisive" lines) and a sponsor-like intro and outro. The `[cuts]` limits are lowered so
    the request runs by map/reduce the way a long video does on a small-context model."""
    named: dict[str, list[str]] = {
        "intro": [
            f"Welcome back everyone, today we have a very long walkthrough, part {j}."
            for j in range(LONG_EDGE_LINES)
        ]
    }
    for k in range(LONG_FILLER_SECTIONS):
        named[f"filler{k:02d}"] = [
            f"In part {k} of the walkthrough we cover point {j} at a relaxed pace today."
            for j in range(LONG_SECTION_LINES)
        ]
        if k in (4, 9):
            key = f"key{len([n for n in named if n.startswith('key')]) + 1}"
            named[key] = [
                f"The decisive step {j} of the {key} fix goes exactly like this."
                for j in range(LONG_KEY_LINES)
            ]
    named["outro"] = [
        f"That is all for this very long one, thanks for watching, goodbye {j}."
        for j in range(LONG_EDGE_LINES)
    ]
    lay = _Layout(named)
    skip = lay.span("intro", "outro")
    key = lay.span("key1", "key2")
    transcript = _make(
        "bench-long",
        "A three-hour walkthrough",
        "Long Talks",
        "A very long walkthrough.\n",
        lay,
        [
            BenchRequest(
                name="decisive-steps",
                instruction="Only the decisive steps of the fixes, nothing else.",
                preset_id=None,
                keep=key,
                skip=skip,
                budget_s=1500.0,
            ),
            BenchRequest(
                name="highlights-5min",
                instruction=preset_instruction("cut-highlights-5"),
                preset_id="cut-highlights-5",
                keep=key,
                skip=skip,
                budget_s=1500.0,
            ),
        ],
    )
    transcript.cuts_overrides = {
        "max_input_tokens": LONG_MAX_INPUT_TOKENS,
        "map_chunk_tokens": LONG_CHUNK_TOKENS,
    }
    return transcript


TRANSCRIPTS: list[BenchTranscript] = [
    _fixture_router(),
    _fixture_sourdough(),
    _fixture_sleep(),
    _fixture_charger(),
    _fixture_projector(),
]

LONG_TRANSCRIPT = _fixture_long()
"""The long-video case: run by map/reduce. Kept out of `TRANSCRIPTS` (the model sees many calls
and the run is slower); `score_all(..., long_video=True)` and `cut_bench.py --long` add it."""


# ---- the scorer ---------------------------------------------------------------------------------

ModelFn = Callable[[list[dict[str, str]]], tuple[str, dict[str, Any]]]
"""The model call the scorer makes: messages in, `(answer text, usage dict)` out."""


@dataclass
class RequestResult:
    """One scored request: how much of the marked keep time survived, what leaked."""

    transcript: str
    request: str
    model: str
    keep: float = 0.0
    skip: float = 0.0
    score: float = 0.0
    refused: str | None = None
    format_error: str | None = None
    repairs: int = 0
    parts: int = 0
    kept_s: float | None = None
    target_s: int | None = None
    length_err: float | None = None  # |kept - target| / target, only for requests with a target
    excess: float = 0.0
    wall_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    def row(self) -> str:
        state = (
            "ok"
            if self.refused is None and self.format_error is None
            else (f"refused: {self.refused}" if self.refused else f"format: {self.format_error}")
        )
        extra = f" excess {self.excess:.2f}" if self.excess else ""
        if self.length_err is not None:
            extra += f" len-err {self.length_err:.2f}"
        return (
            f"{self.transcript:<16} {self.request:<18} keep {self.keep:5.2f} "
            f"skip {self.skip:5.2f} score {self.score:+5.2f} parts {self.parts:<3}"
            f" repairs {self.repairs}{extra} {state}"
        )


def _overlap_ms(span: tuple[float, float], parts: list[Part]) -> float:
    """How much of `span` (s) the kept parts (ms) cover, in ms."""
    a, b = span[0] * 1000, span[1] * 1000
    total = 0.0
    for part in parts:
        total += max(0.0, min(part.end_ms, b) - max(part.start_ms, a))
    return total


class _BenchLLM:
    """The engine's model client over the bench's synchronous `model_fn` (long-video requests)."""

    def __init__(self, model_fn: ModelFn, out: RequestResult):
        self.model_fn, self.out = model_fn, out

    async def chat_json(self, task: LLMTask, messages: list[dict[str, str]], **_: Any) -> Any:
        text, usage = self.model_fn(messages)
        self.out.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.out.completion_tokens += int(usage.get("completion_tokens") or 0)
        try:
            return extract_json(text)
        except ValueError:
            raise LLMError("the answer was not JSON") from None


def _one_pass(
    model_fn: ModelFn,
    units: list[Unit],
    chapters: list[tuple[float, str]],
    meta: dict[str, Any],
    request: BenchRequest,
    target_s: int | None,
    cfg: CutsConfig,
    out: RequestResult,
) -> tuple[Any, list[Part]]:
    """The whole transcript in one request, with the engine's one repair round and, with a
    target length, the same one retry that names the measured shortfall."""
    message = serialize_units(
        units, chapters, meta, request.instruction, target_s, cfg.over_ask_frac
    )
    messages = [
        {"role": "system", "content": CUT_SYSTEM},
        {"role": "user", "content": message},
    ]
    problem: str | None = None
    total_s = 0
    for attempt in range(2 if target_s else 1):
        ask = list(messages)
        if problem:
            ask.append(
                {
                    "role": "user",
                    "content": f"Your previous answer was rejected: {problem} {CUT_JSON_RULES}",
                }
            )
        data = _ask(model_fn, ask, out)
        try:
            parts = parse_cut_answer(data, units)
        except CutFormatError as exc:
            # The engine's one repair round: the model sees why its answer was rejected.
            out.repairs += 1
            data = _ask(
                model_fn,
                [
                    *ask,
                    {
                        "role": "user",
                        "content": f"Your previous answer was rejected: {exc.problem} "
                        f"{CUT_JSON_RULES}",
                    },
                ],
                out,
            )
            parts = parse_cut_answer(data, units)
        if not target_s:
            return data, parts
        parts, total_s = select_for_target(parts, units, cfg, target_s, meta.get("duration_s"))
        low, high = target_band(target_s, cfg.length_tolerance)
        if total_s >= low:
            return data, parts
        if attempt == 0:
            problem = (
                f"it keeps only {int(total_s)} s in total but the task needs about "
                f"{target_s} s (between {int(low)} and {int(high)} s); keep more parts."
            )
    raise CutRefused(
        f"The model kept only {int(total_s)} s of the {target_s} s this cut aims for, "
        "so no cut was built. Try again."
    )


def score_request(
    transcript: BenchTranscript,
    request: BenchRequest,
    model_fn: ModelFn,
    model: str,
    cfg: CutsConfig | None = None,
) -> RequestResult:
    """Run one request through the real engine pieces and mark it against the spans."""
    cfg = (cfg or CutsConfig()).model_copy(update=transcript.cuts_overrides)
    units = build_units(transcript.segments, cfg)
    meta = {
        "title": transcript.title,
        "channel": transcript.channel,
        "duration_s": transcript.duration_s,
    }
    chapters = parse_chapters(transcript.description)
    out = RequestResult(transcript=transcript.id, request=request.name, model=model)
    target_s = request.target_s or effective_target_s(cfg, request.preset_id, transcript.duration_s)
    out.target_s = target_s
    engine = CutEngine(cfg, lambda: LLMTask(model=model), _BenchLLM(model_fn, out))
    started = time.monotonic()
    try:
        if engine.fits(units, chapters, meta, request.instruction, target_s):
            data, parts = _one_pass(model_fn, units, chapters, meta, request, target_s, cfg, out)
        else:
            _data, parts = asyncio.run(
                engine.pick_parts(units, chapters, meta, request.instruction, target_s)
            )
    except CutFormatError as exc:
        out.format_error = exc.problem
        out.wall_s = time.monotonic() - started
        return out
    except ValueError:
        out.format_error = "the answer was not the JSON object"
        out.wall_s = time.monotonic() - started
        return out
    except (CutRefused, LLMError) as exc:
        out.refused = exc.message if isinstance(exc, CutRefused) else "the model did not answer"
        out.wall_s = time.monotonic() - started
        return out
    out.wall_s = time.monotonic() - started
    try:
        min_guard, max_guard = keep_guards(request.preset_id)
        if target_s is not None:
            min_guard = max_guard = False
        kept, _kept_s = finalize_parts(
            parts,
            cfg,
            guard=True,
            duration_s=transcript.duration_s,
            min_guard=min_guard,
            guard_max=max_guard,
        )
    except CutRefused as exc:
        out.refused = exc.message
        return out
    out.parts = len(kept)
    out.kept_s = sum(p.end_ms - p.start_ms for p in kept) / 1000.0
    if target_s:
        out.length_err = round(abs(out.kept_s - target_s) / target_s, 4)
    keep_ms = sum(b - a for a, b in request.keep) * 1000
    skip_ms = sum(b - a for a, b in request.skip) * 1000
    covered = sum(_overlap_ms(span, kept) for span in request.keep)
    leaked = sum(_overlap_ms(span, kept) for span in request.skip)
    out.keep = round(min(1.0, covered / keep_ms), 4) if keep_ms else 1.0
    out.skip = round(max(0.0, 1.0 - leaked / skip_ms), 4) if skip_ms else 1.0
    budget_s = request.budget_s if request.budget_s is not None else 1.5 * keep_ms / 1000.0
    if kept_s := out.kept_s:
        over = max(0.0, kept_s - budget_s)
        out.excess = round(over / transcript.duration_s, 4)
    out.score = round(out.keep - (1.0 - out.skip) - out.excess, 4)
    return out


def _ask(model_fn: ModelFn, messages: list[dict[str, str]], out: RequestResult) -> Any:
    """The model's parsed answer with the engine's one repair round."""
    text, usage = model_fn(messages)
    out.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    out.completion_tokens += int(usage.get("completion_tokens") or 0)
    try:
        return extract_json(text)
    except ValueError:
        pass
    out.repairs += 1
    repair = [
        *messages,
        {
            "role": "user",
            "content": f"Your previous answer was rejected: the answer was not the JSON object. {CUT_JSON_RULES}",
        },
    ]
    text, usage = model_fn(repair)
    out.prompt_tokens += int(usage.get("prompt_tokens") or 0)
    out.completion_tokens += int(usage.get("completion_tokens") or 0)
    return extract_json(text)  # ValueError -> CutFormatError is raised by the caller


def score_transcript(
    transcript: BenchTranscript, model_fn: ModelFn, model: str, cfg: CutsConfig | None = None
) -> list[RequestResult]:
    return [
        score_request(transcript, request, model_fn, model, cfg) for request in transcript.requests
    ]


def score_all(
    model_fn: ModelFn, model: str, cfg: CutsConfig | None = None, *, long_video: bool = False
) -> list[RequestResult]:
    out: list[RequestResult] = []
    for transcript in [*TRANSCRIPTS, *([LONG_TRANSCRIPT] if long_video else [])]:
        out.extend(score_transcript(transcript, model_fn, model, cfg))
    return out


def summarize(results: list[RequestResult]) -> dict[str, Any]:
    """The per-model line the comparison is read from."""
    n = len(results) or 1
    errs = [r.length_err for r in results if r.length_err is not None]
    return {
        "model": results[0].model if results else "?",
        "requests": len(results),
        "mean_keep": round(sum(r.keep for r in results) / n, 4),
        "mean_skip": round(sum(r.skip for r in results) / n, 4),
        "mean_excess": round(sum(r.excess for r in results) / n, 4),
        "mean_length_err": round(sum(errs) / len(errs), 4) if errs else None,
        "mean_score": round(sum(r.score for r in results) / n, 4),
        "refused": sum(1 for r in results if r.refused),
        "format_errors": sum(1 for r in results if r.format_error),
        "repairs": sum(r.repairs for r in results),
        "mean_wall_s": round(sum(r.wall_s for r in results) / n, 1),
        "prompt_tokens": sum(r.prompt_tokens for r in results),
        "completion_tokens": sum(r.completion_tokens for r in results),
    }
