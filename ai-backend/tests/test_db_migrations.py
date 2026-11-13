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
