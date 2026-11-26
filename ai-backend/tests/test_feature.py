from __future__ import annotations

from utubot.config import LLMTask
from utubot.db import Database
from utubot.feature import (
    FeatureStore,
    FeatureUsage,
    cost_for,
    feature_run,
    median_p90,
    run_accumulate,
)

VID = "abcdefghijk"
# the config default model for these features is "worker"; a distinct alias proves a switch moved.
NEW_ALIAS = "smart"


async def test_admin_features_page_lists_features_and_aliases(env):
    r = await env.client.get("/v1/admin/features")
    assert r.status_code == 200
    body = r.json()
    features = {f["feature"]: f for f in body["features"]}
    # triage, summary, answer, analysis and captions are configured by default; glance/cuts are not.
    for f in ("summary", "answer", "triage", "analysis", "captions"):
        assert f in features
    assert "glance" not in features and "cuts" not in features
    # the default alias is the config model, not yet overridden, with an empty audit trail
    assert features["analysis"]["alias"] == "worker"
    assert features["analysis"]["overridden"] is False
    assert features["analysis"]["changes"] == []
    assert features["analysis"]["usage"]["calls"] == 0
    # the switch is validated against the mock's models plus the known config aliases
    assert set(body["aliases"]) >= {"fast", "worker", "smart", "llama3.1:8b"}


async def test_set_alias_routes_the_next_call(env):
    # point the analysis feature (served by the insight endpoint) away from its default
    r = await env.client.put("/v1/admin/features/analysis", json={"alias": NEW_ALIAS})
    assert r.status_code == 200
    payload = r.json()
    assert payload["alias"] == NEW_ALIAS and payload["overridden"] is True
    # the choice is effective on the very next call, with no restart
    await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    assert NEW_ALIAS in [c["model"] for c in env.llm.calls]
    # and the change is logged for the admin audit trail
    assert payload["changes"][0]["to"] == NEW_ALIAS and payload["changes"][0]["by"] == "owner"


async def test_unknown_alias_is_refused_and_not_applied(env):
    r = await env.client.put("/v1/admin/features/analysis", json={"alias": "not-a-model"})
    assert r.status_code == 400
    # nothing was applied: the feature still runs on its config default
    assert env.svc.llm.features.override_for("analysis") is None
    row = next(
        f
        for f in (await env.client.get("/v1/admin/features")).json()["features"]
        if f["feature"] == "analysis"
    )
    assert row["alias"] == "worker" and row["overridden"] is False


async def test_set_empty_alias_is_refused(env):
    r = await env.client.put("/v1/admin/features/analysis", json={"alias": "   "})
    assert r.status_code == 400


async def test_unknown_feature_is_refused(env):
    r = await env.client.put("/v1/admin/features/glance", json={"alias": "worker"})
    assert r.status_code == 400
    r = await env.client.delete("/v1/admin/features/glance")
    assert r.status_code == 400


async def test_reset_returns_to_config_default(env):
    await env.client.put("/v1/admin/features/analysis", json={"alias": NEW_ALIAS})
    r = await env.client.delete("/v1/admin/features/analysis")
    assert r.status_code == 200
    assert r.json()["alias"] == "worker" and r.json()["overridden"] is False
    # a second reset has nothing to drop
    r = await env.client.delete("/v1/admin/features/analysis")
    assert r.status_code == 404


async def test_response_carries_cost_and_elapsed(env):
    r = await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready" and body["key_points"] == ["a", "b"]
    assert "cost_usd" in body and "elapsed_s" in body
    assert isinstance(body["cost_usd"], (int, float))
    assert body["elapsed_s"] >= 0.0


async def test_cost_is_recorded_in_feature_calls(env):
    await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    rows = env.svc.db.all("SELECT feature, alias FROM feature_calls WHERE feature=?", ["analysis"])
    assert rows, "the insight call should record its alias in feature_calls"
    assert rows[0]["alias"] == "worker"


async def test_cost_is_unknown_without_a_price(env):
    # no per-alias price is configured, so the cost is reported as unknown rather than guessed
    assert env.cfg.usage.price_usd_per_million == {}
    await env.client.get(f"/v1/videos/{VID}/insight", params={"wait_ms": 5000})
    row = env.svc.db.one(
        "SELECT cost FROM feature_calls WHERE feature=? AND alias=?",
        ["analysis", "worker"],
    )
    assert row["cost"] is None


def test_cost_for_unknown_without_price(cfg):
    assert cost_for(cfg, "worker", 1_000, 500) is None


def test_cost_for_estimated_from_price(cfg):
    cfg.usage.price_usd_per_million = {"worker": 2.0}
    # 1500 tokens at $2 per 1M tokens = $0.003
    assert cost_for(cfg, "worker", 1_000, 500) == 0.003


def test_median_p90_values():
    assert median_p90([]) == (None, None)
    assert median_p90([100.0]) == (100.0, 100.0)
    # median of [10,20,30,40] is 25; the 90th percentile interpolates to 37
    assert median_p90([10.0, 20.0, 30.0, 40.0]) == (25.0, 37.0)


def test_feature_usage_records_stats_and_sweep():
    db = Database(":memory:")
    usage = FeatureUsage(db)
    # an empty feature reports zeroed, unknown stats
    assert usage.stats("analysis", "worker", 7)["calls"] == 0
    usage.record("analysis", "worker", 120, 1_000, 500, 0.003)
    usage.record("analysis", "worker", 300, 2_000, 1_000, 0.006)
    stats = usage.stats("analysis", "worker", 7)
    assert stats["calls"] == 2
    assert stats["prompt_tokens"] == 3_000
    assert stats["completion_tokens"] == 1_500
    assert stats["tokens"] == 4_500
    assert stats["cost"] == 0.009
    assert stats["median_ms"] == 210.0
    assert stats["samples"] == 2
    # a sweep drops rows older than the retention window (there are none here)
    assert usage.sweep(30) == 0


def test_feature_run_accumulates_cost_and_time():
    with feature_run() as run:
        assert run is not None
        run_accumulate(0.001)
        run_accumulate(0.002)
        run_accumulate(None)  # unknown cost is ignored
        run_accumulate(0.0)  # a zero cost is ignored
    assert run["cost"] == 0.003
    assert run["elapsed_s"] >= 0.0


def test_feature_store_override_and_current_alias():
    db = Database(":memory:")
    store = FeatureStore(cfg_for_store(), db)
    # the feature runs on its config default until the admin overrides it
    assert store.override_for("analysis") is None
    assert store.current_alias("analysis") == "worker"
    doc = store.set_alias("analysis", "smart", "owner")
    assert doc["alias"] == "smart" and doc["overridden"] is True
    # the override wins over the config default for what the feature runs on now
    assert store.current_alias("analysis") == "smart"
    # resetting drops the override and returns to the config default
    assert store.reset("analysis", "owner")["alias"] == "worker"
    assert store.current_alias("analysis") == "worker"


def cfg_for_store():
    from utubot.config import Config, UsageConfig

    c = Config()
    # a store with a plain analysis task whose default model is the "worker" alias.
    c.llm.analysis = LLMTask(model="worker", max_tokens=900)
    c.usage = UsageConfig()
    return c
