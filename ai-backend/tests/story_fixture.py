"""An invented story for the story-cut tests: 24 beats of 30 s (12 minutes), no real film."""

from __future__ import annotations

import json

from utubot import story
from utubot.cuts import Unit

BEATS = 24
UNITS_PER_BEAT = 3
UNIT_S = 10.0
BEAT_S = UNITS_PER_BEAT * UNIT_S
DURATION_S = BEATS * BEAT_S
# beat id -> beats it needs (earlier only); beat 20 is the ending and rests on 3 and 11
NEEDS = {5: [2], 8: [5], 11: [3], 14: [8], 17: [11, 14], 20: [11, 17], 23: [20], 24: [23]}
KINDS = {2: "setup", 3: "setup", 5: "payoff", 8: "turn", 11: "reveal", 20: "payoff", 24: "payoff"}


def units() -> list[Unit]:
    return [
        Unit(n, (n - 1) * UNIT_S, n * UNIT_S - 1.0, f"Line {n} of the invented story.")
        for n in range(1, BEATS * UNITS_PER_BEAT + 1)
    ]


def read_answer() -> dict:
    scenes = []
    for s in range(BEATS // 4):
        beats = []
        for b in range(4):
            beat = s * 4 + b
            first = beat * UNITS_PER_BEAT + 1
            beats.append(
                {"from": first, "to": first + UNITS_PER_BEAT - 1, "what": f"Event {beat + 1}"}
            )
        scenes.append(
            {
                "from": beats[0]["from"],
                "to": beats[-1]["to"],
                "where": f"Place {s}",
                "who": ["c1"],
                "beats": beats,
            }
        )
    return {
        "kind": "story",
        "language": "en",
        "synopsis": "An invented tale.",
        "cast": [{"id": "c1", "name": "Mara", "aliases": [], "role": "hero"}],
        "scenes": scenes,
    }


def link_answer() -> dict:
    rows = [
        {
            "id": i,
            "kind": KINDS.get(i, "connective"),
            "weight": 5 if i in (3, 11, 20, 24) else 2,
            "needs": NEEDS.get(i, []),
            "why": "",
        }
        for i in range(1, BEATS + 1)
    ]
    return {
        "threads": [{"id": "t1", "title": "Main", "beats": list(range(1, BEATS + 1))}],
        "beats": rows,
        "ending": [24],
    }


def story_map() -> story.StoryMap:
    us = units()
    smap = story.StoryMap("story", "en", "An invented tale.", [], [])
    for i in range(1, BEATS + 1):
        first = (i - 1) * UNITS_PER_BEAT
        smap.beats.append(
            story.Beat(
                i,
                (i - 1) // 4 + 1,
                us[first].n,
                us[first + 2].n,
                us[first].start,
                us[first + 2].end + 1.0,
                f"Event {i}",
            )
        )
    parsed = story.parse_link(link_answer(), smap, story.StoryParams(), strict=True)
    story.apply_link(smap, parsed, story.StoryParams())
    return smap


def scripted(*answers: dict | str):
    """A model callable that returns the given answers in order (dicts as JSON)."""
    queue = list(answers)

    def fn(messages):
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        text = item if isinstance(item, str) else json.dumps(item)
        return story.Reply(text, 100, 50, 0.5)

    return fn
