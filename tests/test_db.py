"""
tests/test_db.py

Tests for src/db.py — the SQLite alumni data loader.

All tests seed a fresh temporary database using tmp_path so the real
data/alumni.db is never touched during the test run.

The central guarantee tested here:
    load_alumni_profiles_db() must return a list[dict] that is
    field-for-field and value-for-value identical to the output of
    load_alumni_profiles_csv() for the same source data.
"""

import json
import sqlite3

import pytest

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.db import load_alumni_profiles_db
from src.matching_engine import load_alumni_profiles_csv, rank_alumni


# ---------------------------------------------------------------------------
# Fixture: seeded temporary database
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path) -> str:
    """Seed a fresh SQLite database and return its path."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    return db_path


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------

def test_load_alumni_profiles_db_returns_list(seeded_db):
    """load_alumni_profiles_db() must return a list."""
    result = load_alumni_profiles_db(seeded_db)
    assert isinstance(result, list)


def test_load_alumni_profiles_db_returns_correct_count(seeded_db):
    """Must return one profile per row in the alumni table (6 for sample data)."""
    result = load_alumni_profiles_db(seeded_db)
    assert len(result) == 6


def test_load_alumni_profiles_db_each_item_is_dict(seeded_db):
    """Every item in the returned list must be a dict."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert isinstance(profile, dict)


def test_load_alumni_profiles_db_required_keys_present(seeded_db):
    """Every profile dict must contain all eight required keys."""
    required = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert required.issubset(profile.keys()), (
            f"Profile {profile.get('alumni_id')} is missing keys: "
            f"{required - profile.keys()}"
        )


def test_load_alumni_profiles_db_no_extra_keys(seeded_db):
    """Profiles must not contain extra keys beyond the eight expected ones."""
    expected = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert profile.keys() == expected, (
            f"Profile {profile.get('alumni_id')} has unexpected keys: "
            f"{profile.keys() - expected}"
        )


# ---------------------------------------------------------------------------
# Field types
# ---------------------------------------------------------------------------

def test_load_alumni_profiles_db_skills_are_lists(seeded_db):
    """skills must be a Python list, not a JSON string."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert isinstance(profile["skills"], list), (
            f"skills for {profile['alumni_id']} should be list, "
            f"got {type(profile['skills'])}"
        )


def test_load_alumni_profiles_db_interests_are_lists(seeded_db):
    """interests must be a Python list, not a JSON string."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert isinstance(profile["interests"], list), (
            f"interests for {profile['alumni_id']} should be list, "
            f"got {type(profile['interests'])}"
        )


def test_load_alumni_profiles_db_engagement_score_is_float(seeded_db):
    """engagement_score must be a float."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert isinstance(profile["engagement_score"], float), (
            f"engagement_score for {profile['alumni_id']} should be float, "
            f"got {type(profile['engagement_score'])}"
        )


def test_load_alumni_profiles_db_engagement_score_bounded(seeded_db):
    """engagement_score must be in the range 0.0–1.0."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        assert 0.0 <= profile["engagement_score"] <= 1.0, (
            f"engagement_score {profile['engagement_score']} for "
            f"{profile['alumni_id']} is out of bounds"
        )


def test_load_alumni_profiles_db_skills_are_lowercase(seeded_db):
    """All skill strings must be lowercase (normalization carried through from seed)."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        for skill in profile["skills"]:
            assert skill == skill.lower(), (
                f"Skill '{skill}' in {profile['alumni_id']} is not lowercase"
            )


def test_load_alumni_profiles_db_interests_are_lowercase(seeded_db):
    """All interest strings must be lowercase."""
    result = load_alumni_profiles_db(seeded_db)
    for profile in result:
        for interest in profile["interests"]:
            assert interest == interest.lower(), (
                f"Interest '{interest}' in {profile['alumni_id']} is not lowercase"
            )


# ---------------------------------------------------------------------------
# Specific known-value assertions (Alice: A001)
# ---------------------------------------------------------------------------

def test_load_alumni_profiles_db_alice_engagement_normalized(seeded_db):
    """A001 engagement_score was 75 in the CSV — must be 0.75 from the DB."""
    result = load_alumni_profiles_db(seeded_db)
    alice = next(p for p in result if p["alumni_id"] == "A001")
    assert alice["engagement_score"] == pytest.approx(0.75)


def test_load_alumni_profiles_db_carol_engagement_na_is_zero(seeded_db):
    """A003 engagement_score was 'N/A' in the CSV — must be 0.0 from the DB."""
    result = load_alumni_profiles_db(seeded_db)
    carol = next(p for p in result if p["alumni_id"] == "A003")
    assert carol["engagement_score"] == 0.0


def test_load_alumni_profiles_db_alice_skills_parsed(seeded_db):
    """A001 skills must be the parsed Python list, not a JSON string."""
    result = load_alumni_profiles_db(seeded_db)
    alice = next(p for p in result if p["alumni_id"] == "A001")
    assert alice["skills"] == ["python", "sql", "data analysis"]


# ---------------------------------------------------------------------------
# Output compatibility: DB loader == CSV loader (the central guarantee)
# ---------------------------------------------------------------------------

def test_db_loader_output_matches_csv_loader_output(seeded_db):
    """
    The central compatibility test.

    load_alumni_profiles_db() and load_alumni_profiles_csv() must return
    identical profile dicts when called against the same source data.

    Both outputs are sorted by alumni_id before comparison to eliminate any
    ordering difference between the two loaders.

    Passing this test guarantees that the matching engine (rank_alumni) will
    produce the same results regardless of which loader supplies the profiles.
    """
    db_profiles = sorted(
        load_alumni_profiles_db(seeded_db),
        key=lambda p: p["alumni_id"],
    )
    csv_profiles = sorted(
        load_alumni_profiles_csv(DEFAULT_CSV_PATH),
        key=lambda p: p["alumni_id"],
    )
    assert db_profiles == csv_profiles


# ---------------------------------------------------------------------------
# Matching engine compatibility: same inputs produce same ranking
# ---------------------------------------------------------------------------

def test_rank_alumni_produces_same_ranking_from_db_and_csv(seeded_db):
    """
    End-to-end engine compatibility test.

    rank_alumni() called with DB-loaded profiles must return results in the
    same alumni_id order as when called with CSV-loaded profiles, for the
    same request. This proves the DB path is a drop-in replacement for the
    CSV path in the API layer.
    """
    request = {
        "skills": ["python", "sql"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    db_profiles = load_alumni_profiles_db(seeded_db)
    csv_profiles = load_alumni_profiles_csv(DEFAULT_CSV_PATH)

    db_results = rank_alumni(request, db_profiles)
    csv_results = rank_alumni(request, csv_profiles)

    db_order = [r["alumni_id"] for r in db_results]
    csv_order = [r["alumni_id"] for r in csv_results]

    assert db_order == csv_order, (
        f"Ranking order differs between DB and CSV loaders.\n"
        f"  DB  order: {db_order}\n"
        f"  CSV order: {csv_order}"
    )


def test_rank_alumni_produces_same_scores_from_db_and_csv(seeded_db):
    """
    rank_alumni() must produce the same total_score for each alumni_id
    regardless of whether profiles came from the DB or CSV loader.
    """
    request = {
        "skills": ["python", "sql"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    db_results = rank_alumni(request, load_alumni_profiles_db(seeded_db))
    csv_results = rank_alumni(request, load_alumni_profiles_csv(DEFAULT_CSV_PATH))

    db_scores = {r["alumni_id"]: r["total_score"] for r in db_results}
    csv_scores = {r["alumni_id"]: r["total_score"] for r in csv_results}

    for alumni_id in csv_scores:
        assert db_scores[alumni_id] == pytest.approx(csv_scores[alumni_id]), (
            f"{alumni_id}: DB score {db_scores[alumni_id]:.6f} != "
            f"CSV score {csv_scores[alumni_id]:.6f}"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_load_alumni_profiles_db_raises_if_file_not_found(tmp_path):
    """Must raise FileNotFoundError when the database file does not exist."""
    with pytest.raises(FileNotFoundError):
        load_alumni_profiles_db(str(tmp_path / "does_not_exist.db"))


def test_load_alumni_profiles_db_raises_if_table_missing(tmp_path):
    """Must raise sqlite3.OperationalError when the alumni table does not exist."""
    db_path = str(tmp_path / "empty.db")
    sqlite3.connect(db_path).close()  # create an empty DB file
    with pytest.raises(Exception):  # sqlite3.OperationalError
        load_alumni_profiles_db(db_path)
