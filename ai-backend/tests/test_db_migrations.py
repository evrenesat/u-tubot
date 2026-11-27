"""Rollback safety: the revision before this one must run on the database this one leaves behind.

The backend only ever adds (`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN`). A column added to an existing table must be nullable or have a
default, because older code inserts rows without naming it; a NOT NULL column without a default would make every such INSERT fail.
"""

from __future__ import annotations

import pytest

from utubot import db

ADDED_COLUMNS = {
    name: value
    for name, value in vars(db).items()
    if name.endswith("_COLUMNS") and isinstance(value, dict)
}


def test_added_columns_are_found():
    assert {"JOB_COLUMNS", "POLICY_COLUMNS", "TRANSCRIPT_COLUMNS", "CAPTION_COLUMNS"} <= set(
        ADDED_COLUMNS
    )


@pytest.mark.parametrize("group", sorted(ADDED_COLUMNS))
def test_every_added_column_is_nullable_or_has_a_default(group):
    for column, ddl in ADDED_COLUMNS[group].items():
        upper = ddl.upper()
        assert "NOT NULL" not in upper or "DEFAULT" in upper, (
            f"{group}.{column} is NOT NULL without a DEFAULT; an older revision could not insert into the table"
        )


def test_caption_tracks_gain_the_timing_columns_additively():
    assert db.CAPTION_COLUMNS["timing_version"] == "INTEGER"
    assert db.CAPTION_COLUMNS["timing"] == "TEXT"
    database = db.Database(":memory:")
    columns = {row["name"] for row in database.all("PRAGMA table_info(captions)")}
    assert {"job_id", "timing_version", "timing"} <= columns
    # a row written the way the previous revision does it (without the new columns) is accepted
    database.execute(
        "INSERT INTO captions(video_id,lang,label,speakers,vtt,created_at,job_id)"
        " VALUES('v','en','l',0,'WEBVTT',0,NULL)"
    )
    assert database.one("SELECT timing_version FROM captions")["timing_version"] is None
    database.close()


def test_an_old_cut_requests_table_gains_refetch_additively(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cut_requests(id TEXT PRIMARY KEY, user TEXT NOT NULL, video_id TEXT NOT NULL,"
        " state TEXT NOT NULL DEFAULT 'building', created_at REAL NOT NULL DEFAULT 0)"
    )
    conn.execute("INSERT INTO cut_requests(id,user,video_id) VALUES('r','u','v')")
    conn.commit()
    conn.close()
    database = db.Database(str(path))
    assert database.one("SELECT refetch FROM cut_requests WHERE id='r'")["refetch"] == 0
    database.close()
