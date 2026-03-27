"""
tests/test_seed_database.py

Tests for execution/seed_database.py.

All tests use pytest's tmp_path fixture to write to a temporary DB file so
the real data/alumni.db is never touched during testing.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from execution.seed_database import (
    DEFAULT_CSV_PATH,
    _parse_engagement,
    _parse_list,
    seed,
)
from src.matching_engine import load_alumni_profiles_csv


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read_all(db_path: str) -> list[dict]:
    """Read all rows from the alumni table and return as list[dict]."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM alumni ORDER BY alumni_id").fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Unit tests for normalization helpers
# ---------------------------------------------------------------------------

def test_parse_list_splits_and_lowercases():
    assert _parse_list("Python, SQL, Data Analysis") == ["python", "sql", "data analysis"]


def test_parse_list_filters_empty_items():
    assert _parse_list("  , python,  , sql") == ["python", "sql"]


def test_parse_list_empty_string_returns_empty_list():
    assert _parse_list("") == []


def test_parse_engagement_normalizes_0_to_100_scale():
    assert _parse_engagement("75") == pytest.approx(0.75)


def test_parse_engagement_leaves_already_normalized_value():
    assert _parse_engagement("0.8") == pytest.approx(0.8)


def test_parse_engagement_na_becomes_zero():
    assert _parse_engagement("N/A") == 0.0


def test_parse_engagement_blank_becomes_zero():
    assert _parse_engagement("") == 0.0
    assert _parse_engagement("   ") == 0.0


# ---------------------------------------------------------------------------
# Seed function: file and schema
# ---------------------------------------------------------------------------

def test_seed_creates_database_file(tmp_path):
    """seed() must create the DB file at the given path."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    assert Path(db_path).exists()


def test_seed_creates_alumni_table(tmp_path):
    """The alumni table must exist after seeding."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    con = sqlite3.connect(db_path)
    try:
        tables = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='alumni'"
        ).fetchall()
    finally:
        con.close()

    assert len(tables) == 1


def test_seed_returns_correct_row_count(tmp_path):
    """seed() must return the number of rows upserted (6 from sample CSV)."""
    db_path = str(tmp_path / "alumni.db")
    count = seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    assert count == 6


def test_seed_inserts_correct_number_of_rows(tmp_path):
    """After seeding, the alumni table must contain exactly 6 rows."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    con = sqlite3.connect(db_path)
    try:
        count = con.execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
    finally:
        con.close()

    assert count == 6


# ---------------------------------------------------------------------------
# Seed function: data correctness
# ---------------------------------------------------------------------------

def test_seed_skills_stored_as_json_list(tmp_path):
    """Skills must be stored as a JSON array, not a raw string."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    for row in rows:
        skills = json.loads(row["skills"])
        assert isinstance(skills, list), f"skills for {row['alumni_id']} should be a list"


def test_seed_interests_stored_as_json_list(tmp_path):
    """Interests must be stored as a JSON array, not a raw string."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    for row in rows:
        interests = json.loads(row["interests"])
        assert isinstance(interests, list), f"interests for {row['alumni_id']} should be a list"


def test_seed_skills_are_lowercase(tmp_path):
    """All skill strings in the DB must be lowercase."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    for row in rows:
        for skill in json.loads(row["skills"]):
            assert skill == skill.lower(), f"Skill '{skill}' in {row['alumni_id']} is not lowercase"


def test_seed_engagement_score_normalized(tmp_path):
    """Engagement score of 75 in CSV must be stored as 0.75 in the DB."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    alice = next(r for r in rows if r["alumni_id"] == "A001")
    assert alice["engagement_score"] == pytest.approx(0.75)


def test_seed_engagement_score_na_becomes_zero(tmp_path):
    """Engagement score 'N/A' in CSV must be stored as 0.0 in the DB."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    carol = next(r for r in rows if r["alumni_id"] == "A003")
    frank = next(r for r in rows if r["alumni_id"] == "A006")
    assert carol["engagement_score"] == 0.0
    assert frank["engagement_score"] == 0.0


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_seed_is_idempotent_row_count(tmp_path):
    """Running seed() twice must not increase the row count."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    con = sqlite3.connect(db_path)
    try:
        count = con.execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
    finally:
        con.close()

    assert count == 6


def test_seed_is_idempotent_values(tmp_path):
    """Running seed() twice must produce identical row data both times."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    rows_first = _read_all(db_path)

    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    rows_second = _read_all(db_path)

    assert rows_first == rows_second


# ---------------------------------------------------------------------------
# Correctness: seeded data matches CSV loader output
# ---------------------------------------------------------------------------

def test_seeded_profiles_match_csv_loader_output(tmp_path):
    """
    The most important correctness test.

    Profiles read from the seeded DB (JSON-parsed) must be identical to
    profiles produced by load_alumni_profiles_csv() for the same source file.

    This guarantees the matching engine will produce the same results
    whether it is backed by CSV or the seeded SQLite database.
    """
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    rows = _read_all(db_path)
    db_profiles = sorted(
        [
            {
                "alumni_id": r["alumni_id"],
                "full_name": r["full_name"],
                "email": r["email"],
                "skills": json.loads(r["skills"]),
                "interests": json.loads(r["interests"]),
                "location": r["location"],
                "engagement_score": r["engagement_score"],
                "availability": r["availability"],
            }
            for r in rows
        ],
        key=lambda p: p["alumni_id"],
    )

    csv_profiles = sorted(
        load_alumni_profiles_csv(DEFAULT_CSV_PATH),
        key=lambda p: p["alumni_id"],
    )

    assert db_profiles == csv_profiles


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_seed_raises_if_csv_not_found(tmp_path):
    """seed() must raise FileNotFoundError when the CSV path does not exist."""
    with pytest.raises(FileNotFoundError):
        seed(csv_path=str(tmp_path / "does_not_exist.csv"), db_path=str(tmp_path / "x.db"))
