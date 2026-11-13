"""The per-video stage cache: results of finished stages survive a retry."""

from __future__ import annotations

from utubot.captions.stages import StageCache
from utubot.db import Database


def test_roundtrip():
    cache = StageCache(Database(":memory:"))
    assert cache.get("vid", "asr", "k1") is None
    cache.put("vid", "asr", "k1", {"words": [[0.0, 0.4, "hi"]]})
    assert cache.get("vid", "asr", "k1") == {"words": [[0.0, 0.4, "hi"]]}


def test_keys_are_isolated():
    cache = StageCache(Database(":memory:"))
    cache.put("vid", "asr", "k1", {"a": 1})
    cache.put("vid", "asr", "k2", {"b": 2})
    cache.put("vid2", "asr", "k1", {"c": 3})
    cache.put("vid", "proofread", "k1", {"d": 4})
    assert cache.get("vid", "asr", "k1") == {"a": 1}
    assert cache.get("vid2", "asr", "k1") == {"c": 3}
    assert cache.get("vid", "proofread", "k1") == {"d": 4}


def test_put_overwrites_and_corrupt_rows_read_as_none():
    cache = StageCache(Database(":memory:"))
    cache.put("vid", "asr", "k1", {"a": 1})
    cache.put("vid", "asr", "k1", {"a": 2})
    assert cache.get("vid", "asr", "k1") == {"a": 2}
    cache.db.execute("UPDATE stage_cache SET json='not json' WHERE cache_key='k1'")
    assert cache.get("vid", "asr", "k1") is None
