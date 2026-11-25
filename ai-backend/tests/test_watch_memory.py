from __future__ import annotations

from utubot.watch.memory import BoundedSceneMemory, format_carry, format_recent


def test_bounded_context_keeps_recent_lines_and_carry_state():
    segments = [
        (0.0, 2.0, "old line"),
        (5.0, 6.0, "old two"),
        (8.0, 9.0, "just before"),
        (10.0, 11.0, "recent one"),
    ]
    memory = BoundedSceneMemory(segments, recent_window_count=2, carry_forward_scenes=1)
    memory.record(0.0, 5.0, visual_summary="A slide about builds.", kind="slide", seen=True)
    memory.record(5.0, 10.0, visual_summary="", kind="other", seen=False)
    memory.record(10.0, 15.0, visual_summary="A demo.", kind="demo", seen=True)
    snap = memory.build_snapshot(20.0, 25.0)
    text = "\n".join(snap.recent_lines)
    assert "recent one" in text
    assert "old line" not in text and "just before" not in text
    assert text.count("recent one") == 1
    carry = format_carry(snap.carry_summaries)
    assert "demo" in carry and "A demo." in carry


def test_context_limit_drops_the_oldest_lines_first():
    lines = ["first old", "second", "third new"]
    kept = format_recent(lines, 16)
    assert "first old" not in kept
    assert "third new" in kept


def test_inside_lines_only_the_chunk_window():
    memory = BoundedSceneMemory([(0.0, 1.0, "before"), (4.0, 5.0, "inside")])
    assert memory.inside_lines(3.0, 6.0) == ["4.0-5.0s: inside"]
