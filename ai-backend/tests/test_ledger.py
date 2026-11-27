from __future__ import annotations

import time

from tests.conftest import OTHER_TOKEN
from utubot.db import Database
from utubot.ledger import LedgerService, categorize

VID = "abcdefghijk"  # a valid video id is exactly 11 characters


def test_categorize_known_messages():
    # the four shapes the owner asked for: rate limit, YouTube refusal, model error, and the unknown.
    assert categorize("YouTube 429 rate limited") == ("rate-limited", False)
    assert categorize("this video is private") == ("youtube-refused", False)
    assert categorize("model is busy now") == ("model-error", False)
    assert categorize("something totally weird happened") == ("unknown", True)


def test_categorize_flags_empty_and_unmatched_text():
    assert categorize("") == ("unknown", True)
    assert categorize(None) == ("unknown", True)
    assert categorize("a strange new failure mode") == ("unknown", True)


def test_categorize_returns_the_first_matching_rule():
    # rate limit is listed before YouTube refusal, so a message matching both is counted as rate limited.
    assert categorize("429 too many requests, 403 forbidden") == ("rate-limited", False)
    assert categorize("this video is private") == ("youtube-refused", False)


def test_categorize_explicit_category_wins_and_is_not_flagged():
    assert categorize("anything", category="bug") == ("bug", False)
    # an explicit category outside the known set is triaged, not silently folded in.
    assert categorize("anything", category="typo") == ("unknown", True)


def test_service_records_counts_recent_and_reclassifies():
    db = Database(":memory:")
    ledger = LedgerService(db)

    # a YouTube rate-limit failure and an unmatched one, both for the same video.
    a = ledger.record("job", "captions", video_id="vid1", message="YouTube 429 rate limited")
    b = ledger.record("content", "summary", video_id="vid1", message="a brand new failure shape")
    assert a and b

    # the counts table groups per category per day and adds a per-category total.
    counts = ledger.counts(14)
    by_cat = {c["category"]: c for c in counts}
    assert by_cat["rate-limited"]["count"] == 1 and by_cat["rate-limited"]["total"] == 1
    assert by_cat["unknown"]["count"] == 1 and by_cat["unknown"]["total"] == 1
    assert all(c["flagged"] is False for c in counts if c["category"] == "rate-limited")
    assert by_cat["unknown"]["flagged"] is True

    # the newest failures carry the components and the video they belong to.
    recent = ledger.recent(10)
    assert [r["operation"] for r in recent] == ["summary", "captions"]
    assert all(r["video_id"] == "vid1" for r in recent)

    # triage moves the unknown failure into a real category; the count table then reflects it.
    assert ledger.reclassify(b, "config", "owner") is True
    counts = ledger.counts(14)
    by_cat = {c["category"]: c for c in counts}
    assert by_cat["config"]["total"] == 1 and "unknown" not in by_cat
    # triaging the same failure again is a no-op and reports so.
    assert ledger.reclassify(b, "config", "owner") is False


def test_service_links_a_failure_to_its_job_id():
    db = Database(":memory:")
    ledger = LedgerService(db)
    ledger.record(
        "job", "captions", video_id="vid1", message="ASR failed", detail="job_id=deadbeefcafe"
    )
    (entry,) = ledger.recent(10)
    assert entry["job_id"] == "deadbeefcafe"
    # a non-job failure (a YouTube reason) has no job to link to.
    ledger.record("youtube", "captions", message="YouTube 403 forbidden")
    (youtube_entry,) = ledger.recent(10, category="youtube-refused")
    assert youtube_entry["job_id"] is None


def test_service_sweeps_rows_older_than_the_retention_window():
    db = Database(":memory:")
    db.execute(
        "INSERT INTO failures(ts,component,operation,category,message) VALUES(?,?,?,?,?)",
        [1.0, "job", "captions", "bug", "old"],
    )
    db.execute(
        "INSERT INTO failures(ts,component,operation,category,message) VALUES(?,?,?,?,?)",
        [time.time(), "job", "captions", "bug", "recent"],
    )
    removed = LedgerService(db, keep_days=30).sweep(30)
    assert removed == 1
    assert db.one("SELECT COUNT(*) n FROM failures")["n"] == 1


def test_service_is_a_noop_without_a_database():
    assert LedgerService(None).record("job", "captions", message="x") is None
    assert LedgerService(None).counts(7) == []
    assert LedgerService(None).recent() == []


async def test_admin_ledger_page_requires_admin(env):
    # an unauthenticated request is refused, as is a non-admin user.
    anon = await _anon(env)
    assert (await anon.get("/v1/admin/ledger")).status_code == 401
    partner = client_for(env, OTHER_TOKEN)
    assert (await partner.get("/v1/admin/ledger")).status_code == 403


async def test_client_reports_a_failure_to_the_ledger(env):
    # a client reports its own failure; the backend categorises it from the message.
    r = await env.client.post(
        "/v1/ledger",
        json={"operation": "transcript", "message": "this video is private", "video_id": VID},
    )
    assert r.status_code == 200
    # it lands in the ledger, counted on the admin page.
    page = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()
    assert page["recent"] and page["recent"][0]["category"] == "youtube-refused"
    assert page["recent"][0]["operation"] == "transcript"


async def test_client_report_requires_authentication(env):
    anon = await _anon(env)
    assert (
        await anon.post("/v1/ledger", json={"operation": "x", "message": "boom"})
    ).status_code == 401


async def test_client_report_rejects_a_bad_video_id(env):
    r = await env.client.post(
        "/v1/ledger",
        json={"operation": "transcript", "message": "boom", "video_id": "not a video id"},
    )
    assert r.status_code == 400


async def test_client_report_rejects_an_unknown_category(env):
    # a client may name a known category; an unknown one is rejected (validation errors map to 400 here).
    r = await env.client.post(
        "/v1/ledger", json={"operation": "x", "message": "boom", "category": "typo"}
    )
    assert r.status_code == 400


async def test_admin_triage_reclassifies_a_failure(env):
    await env.client.post("/v1/ledger", json={"operation": "x", "message": "a strange failure"})
    page = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()
    (entry,) = page["recent"]
    assert entry["flagged"] is True and entry["category"] == "unknown"

    r = await env.client.post(
        f"/v1/admin/ledger/{entry['id']}/categorize", json={"category": "config"}
    )
    assert r.status_code == 200 and r.json()["changed"] is True
    # the triaged failure is no longer unknown.
    page = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()
    assert page["recent"][0]["category"] == "config" and page["recent"][0]["flagged"] is False


async def test_admin_triage_refuses_an_unknown_category(env):
    await env.client.post("/v1/ledger", json={"operation": "x", "message": "boom"})
    page = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()
    (entry,) = page["recent"]
    r = await env.client.post(
        f"/v1/admin/ledger/{entry['id']}/categorize", json={"category": "typo"}
    )
    assert r.status_code == 400


async def test_client_report_folds_an_unknown_component_to_client(env):
    await env.client.post(
        "/v1/ledger", json={"operation": "x", "message": "boom", "component": "not-a-real-one"}
    )
    (entry,) = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()[
        "recent"
    ]
    assert entry["component"] == "client"


def test_service_recent_pages_with_offset():
    db = Database(":memory:")
    ledger = LedgerService(db)
    for i in range(15):
        ledger.record("job", "captions", message=f"failure number {i}")
    # the first page is the ten newest, newest first; the second page the five that remain.
    first = ledger.recent(10)
    second = ledger.recent(10, offset=10)
    assert [e["id"] for e in first] == list(range(15, 5, -1))
    assert [e["id"] for e in second] == list(range(5, 0, -1))
    # the pages cover every row exactly once, and an offset past the end is empty.
    assert [e["id"] for e in first + second] == list(range(15, 0, -1))
    assert ledger.recent(10, offset=100) == []
    # paging also applies when filtered by category.
    ledger.record("job", "captions", message="YouTube 429 rate limited")
    assert len(ledger.recent(10, category="rate-limited")) == 1
    assert len(ledger.recent(10, category="rate-limited", offset=10)) == 0


def test_ledger_migration_is_additive(tmp_path):
    # a database from before the ledger opens with the table created on the way in.
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE jobs(id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()
    Database(path)
    assert Database(path).one("SELECT COUNT(*) n FROM failures")["n"] == 0


def client_for(env, token: str):
    import httpx

    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _anon(env):
    import httpx

    return httpx.AsyncClient(
        transport=env.client._transport,
        base_url="http://utubot",
    )


def test_day_is_utc_and_numbers_need_word_boundaries():
    from utubot.ledger import _day, categorize

    assert _day(1_700_000_000.0) == "2023-11-14"
    assert categorize("read 4031 bytes")[1] is True
    assert categorize("HTTP 403 from the player")[0] == "youtube-refused"


async def test_admin_ledger_recent_is_paged_with_offset(env):
    # the admin page walks the newest failures in pages of ten; the server sends them newest first.
    for i in range(15):
        await env.client.post(
            "/v1/ledger", json={"operation": "x", "message": f"failure number {i}"}
        )
    first = (
        await env.client.get(
            "/v1/admin/ledger", params={"period_days": 7, "limit": 10, "offset": 0}
        )
    ).json()
    assert len(first["recent"]) == 10
    second = (
        await env.client.get(
            "/v1/admin/ledger", params={"period_days": 7, "limit": 10, "offset": 10}
        )
    ).json()
    assert len(second["recent"]) == 5
    assert first["recent"][0]["id"] > second["recent"][-1]["id"]
    assert not any(a["id"] == b["id"] for a in first["recent"] for b in second["recent"])
    assert (
        await env.client.get(
            "/v1/admin/ledger", params={"period_days": 7, "limit": 10, "offset": 100}
        )
    ).json()["recent"] == []
    # a negative offset is refused like the other bounds.
    assert (
        await env.client.get("/v1/admin/ledger", params={"period_days": 7, "offset": -1})
    ).status_code == 400


async def test_admin_page_carries_the_youtube_forbidden_metric(env):
    from utubot.usage import METRIC_YOUTUBE_FORBIDDEN, Usage

    Usage(env.svc.db).add(METRIC_YOUTUBE_FORBIDDEN, 3)
    page = (await env.client.get("/v1/admin/ledger", params={"period_days": 7})).json()
    assert page["youtube_forbidden"][0]["count"] == 3
