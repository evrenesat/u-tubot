"""The source columns: old rows mean YouTube, and the optional cut-document source object."""

from __future__ import annotations

from utubot.cuts import source_document, source_matches, source_ref


def test_a_row_without_source_columns_is_youtube():
    ref = source_ref({"video_id": "abcdefghijk"})

    assert ref == {
        "kind": "youtube",
        "key": "youtube:abcdefghijk",
        "release_key": None,
        "release_duration_ms": None,
        "cache_source": "abcdefghijk",
    }
    assert source_document(ref) is None


def test_another_source_has_its_key_and_release():
    ref = source_ref(
        {
            "video_id": "abcdefghijk",
            "source_kind": "imdb",
            "source_key": "imdb:tt0123456:s01e03",
            "release_key": "dur:2400000",
            "release_duration_ms": 2_400_000,
        }
    )

    assert ref["cache_source"] == "imdb:tt0123456:s01e03|dur:2400000"
    assert source_document(ref) == {
        "kind": "imdb",
        "key": "imdb:tt0123456:s01e03",
        "release_key": "dur:2400000",
        "release_duration_ms": 2_400_000,
    }


def test_matching_a_source_compares_key_release_and_length():
    youtube = source_ref({"video_id": "abcdefghijk"})
    assert source_matches(youtube, source_ref({"video_id": "abcdefghijk"}), 2000)

    row = {
        "video_id": "abcdefghijk",
        "source_kind": "imdb",
        "source_key": "imdb:tt0123456:s01e03",
        "release_key": "dvd",
        "release_duration_ms": 60_000,
    }
    left = source_ref(row)
    assert source_matches(left, source_ref({**row, "release_duration_ms": 61_500}), 2000)
    assert not source_matches(left, source_ref({**row, "release_duration_ms": 70_000}), 2000)
    assert not source_matches(left, source_ref({**row, "release_key": "bluray"}), 2000)
    assert not source_matches(
        left,
        source_ref({**row, "source_key": "imdb:tt0123456:s01e04"}),
        2000,
    )
