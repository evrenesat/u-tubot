from __future__ import annotations

from utubot.watch.memory import BoundedSceneMemory, format_carry, format_recent


def test_bounded_context_keeps_recent_lines_and_carry_state():
    segments = [
        (0.0, 2.0, "old line"),
        (5.0, 6.0, "recent one"),
        (8.0, 9.0, "recent two"),
    ]
    memory = BoundedSceneMemory(segments, recent_window_count=3, carry_forward_scenes=1)
    memory.record(0.0, 5.0, visual_summary="A slide about builds.", kind="slide", seen=True)
    snap = memory.build_snapshot(5.0, 10.0)
    assert "recent one" in "\n".join(snap.recent_lines)
    assert "old line" not in "\n".join(snap.recent_lines)
    carry = format_carry(snap.carry_summaries)
    assert "slide" in carry and "A slide about builds." in carry


def test_context_limit_drops_the_oldest_lines_first():
    lines = ["first old", "second", "third new"]
    kept = format_recent(lines, 16)
    assert "first old" not in kept
    assert "third new" in kept


def test_inside_lines_only_the_chunk_window():
    memory = BoundedSceneMemory([(0.0, 1.0, "before"), (4.0, 5.0, "inside")])
    assert memory.inside_lines(3.0, 6.0) == ["4.0-5.0s: inside"]
