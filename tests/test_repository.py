"""
tests/test_repository.py

Tests for src/repository.py — AlumniRepository interface and implementations.

Covers:
    1. Interface compliance (isinstance checks against AlumniRepository)
    2. CsvAlumniRepository: get_all_alumni(), get_alumni_by_id(), not-found
    3. SqliteAlumniRepository: get_all_alumni(), get_alumni_by_id(), not-found
    4. Cross-implementation equivalence: both return identical profile dicts

All SQLite tests use a temporary seeded database via tmp_path.
The real data/alumni.db is never touched.
"""

import sqlite3

import pytest

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.repository import (
    AlumniAlreadyExistsError,
    AlumniNotFoundError,
    AlumniRepository,
    CsvAlumniRepository,
    SqliteAlumniRepository,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path) -> str:
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    return db_path


@pytest.fixture()
def csv_repo() -> CsvAlumniRepository:
    return CsvAlumniRepository(DEFAULT_CSV_PATH)


@pytest.fixture()
def sqlite_repo(seeded_db) -> SqliteAlumniRepository:
    return SqliteAlumniRepository(seeded_db)


# ---------------------------------------------------------------------------
# 1. Interface compliance
# ---------------------------------------------------------------------------

def test_csv_repo_is_alumni_repository(csv_repo):
    """CsvAlumniRepository must be a concrete implementation of AlumniRepository."""
    assert isinstance(csv_repo, AlumniRepository)


def test_sqlite_repo_is_alumni_repository(sqlite_repo):
    """SqliteAlumniRepository must be a concrete implementation of AlumniRepository."""
    assert isinstance(sqlite_repo, AlumniRepository)


# ---------------------------------------------------------------------------
# 2. CsvAlumniRepository
# ---------------------------------------------------------------------------

def test_csv_repo_get_all_alumni_returns_list(csv_repo):
    assert isinstance(csv_repo.get_all_alumni(), list)


def test_csv_repo_get_all_alumni_count(csv_repo):
    """Sample CSV contains 6 alumni records."""
    assert len(csv_repo.get_all_alumni()) == 6


def test_csv_repo_get_all_alumni_each_item_is_dict(csv_repo):
    for profile in csv_repo.get_all_alumni():
        assert isinstance(profile, dict)


def test_csv_repo_get_all_alumni_required_keys(csv_repo):
    required = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    for profile in csv_repo.get_all_alumni():
        assert required.issubset(profile.keys()), (
            f"Profile {profile.get('alumni_id')} missing keys: {required - profile.keys()}"
        )


def test_csv_repo_get_alumni_by_id_found(csv_repo):
    profile = csv_repo.get_alumni_by_id("A001")
    assert profile is not None
    assert profile["alumni_id"] == "A001"


def test_csv_repo_get_alumni_by_id_not_found_returns_none(csv_repo):
    assert csv_repo.get_alumni_by_id("DOES_NOT_EXIST") is None


def test_csv_repo_get_alumni_by_id_returns_correct_profile_for_each_id(csv_repo):
    for alumni_id in ["A001", "A002", "A003", "A004", "A005", "A006"]:
        profile = csv_repo.get_alumni_by_id(alumni_id)
        assert profile is not None, f"Expected profile for {alumni_id}, got None"
        assert profile["alumni_id"] == alumni_id


# ---------------------------------------------------------------------------
# 3. SqliteAlumniRepository
# ---------------------------------------------------------------------------

def test_sqlite_repo_get_all_alumni_returns_list(sqlite_repo):
    assert isinstance(sqlite_repo.get_all_alumni(), list)


def test_sqlite_repo_get_all_alumni_count(sqlite_repo):
    """Seeded DB contains 6 alumni records (matches sample CSV)."""
    assert len(sqlite_repo.get_all_alumni()) == 6


def test_sqlite_repo_get_all_alumni_each_item_is_dict(sqlite_repo):
    for profile in sqlite_repo.get_all_alumni():
        assert isinstance(profile, dict)


def test_sqlite_repo_get_all_alumni_required_keys(sqlite_repo):
    required = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    for profile in sqlite_repo.get_all_alumni():
        assert required.issubset(profile.keys()), (
            f"Profile {profile.get('alumni_id')} missing keys: {required - profile.keys()}"
        )


def test_sqlite_repo_get_alumni_by_id_found(sqlite_repo):
    profile = sqlite_repo.get_alumni_by_id("A001")
    assert profile is not None
    assert profile["alumni_id"] == "A001"


def test_sqlite_repo_get_alumni_by_id_not_found_returns_none(sqlite_repo):
    assert sqlite_repo.get_alumni_by_id("DOES_NOT_EXIST") is None


def test_sqlite_repo_get_alumni_by_id_returns_correct_profile_for_each_id(sqlite_repo):
    for alumni_id in ["A001", "A002", "A003", "A004", "A005", "A006"]:
        profile = sqlite_repo.get_alumni_by_id(alumni_id)
        assert profile is not None, f"Expected profile for {alumni_id}, got None"
        assert profile["alumni_id"] == alumni_id


# ---------------------------------------------------------------------------
# 4. Cross-implementation equivalence
# ---------------------------------------------------------------------------

def test_both_repos_return_same_count(csv_repo, sqlite_repo):
    assert len(csv_repo.get_all_alumni()) == len(sqlite_repo.get_all_alumni())


def test_both_repos_return_identical_profiles(csv_repo, sqlite_repo):
    """
    The central compatibility guarantee: both implementations must return
    the same profile dicts for the same source data.
    """
    csv_profiles = sorted(csv_repo.get_all_alumni(), key=lambda p: p["alumni_id"])
    sqlite_profiles = sorted(sqlite_repo.get_all_alumni(), key=lambda p: p["alumni_id"])
    assert csv_profiles == sqlite_profiles


def test_both_repos_get_alumni_by_id_same_result(csv_repo, sqlite_repo):
    csv_profile = csv_repo.get_alumni_by_id("A001")
    sqlite_profile = sqlite_repo.get_alumni_by_id("A001")
    assert csv_profile == sqlite_profile


def test_both_repos_return_none_for_missing_id(csv_repo, sqlite_repo):
    assert csv_repo.get_alumni_by_id("MISSING") is None
    assert sqlite_repo.get_alumni_by_id("MISSING") is None


# ---------------------------------------------------------------------------
# 5. create_alumni — SqliteAlumniRepository
# ---------------------------------------------------------------------------

_NEW_PROFILE = {
    "alumni_id": "A007",
    "full_name": "Grace Hopper",
    "email": "grace.hopper@example.com",
    "skills": ["python", "fortran"],
    "interests": ["education"],
    "location": "NY",
    "engagement_score": 0.85,
    "availability": "available",
}


def test_sqlite_repo_create_alumni_returns_profile_dict(sqlite_repo):
    """create_alumni() must return a dict with all eight required keys."""
    result = sqlite_repo.create_alumni(_NEW_PROFILE)
    assert isinstance(result, dict)
    required = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    assert required.issubset(result.keys())
    assert result["alumni_id"] == _NEW_PROFILE["alumni_id"]


def test_sqlite_repo_create_alumni_persists_to_database(sqlite_repo, seeded_db):
    """create_alumni() must write the row to the SQLite file."""
    sqlite_repo.create_alumni(_NEW_PROFILE)

    con = sqlite3.connect(seeded_db)
    row = con.execute(
        "SELECT alumni_id FROM alumni WHERE alumni_id = ?",
        (_NEW_PROFILE["alumni_id"],),
    ).fetchone()
    con.close()

    assert row is not None
    assert row[0] == _NEW_PROFILE["alumni_id"]


def test_sqlite_repo_create_alumni_appears_in_get_all_alumni(sqlite_repo):
    """After create_alumni(), get_all_alumni() must include the new profile."""
    sqlite_repo.create_alumni(_NEW_PROFILE)
    ids = [p["alumni_id"] for p in sqlite_repo.get_all_alumni()]
    assert _NEW_PROFILE["alumni_id"] in ids


def test_sqlite_repo_create_alumni_findable_by_get_alumni_by_id(sqlite_repo):
    """After create_alumni(), get_alumni_by_id() must return the new profile."""
    sqlite_repo.create_alumni(_NEW_PROFILE)
    profile = sqlite_repo.get_alumni_by_id(_NEW_PROFILE["alumni_id"])
    assert profile is not None
    assert profile["alumni_id"] == _NEW_PROFILE["alumni_id"]


def test_sqlite_repo_create_alumni_duplicate_id_raises(sqlite_repo):
    """create_alumni() with an existing alumni_id must raise AlumniAlreadyExistsError."""
    with pytest.raises(AlumniAlreadyExistsError) as exc_info:
        sqlite_repo.create_alumni({**_NEW_PROFILE, "alumni_id": "A001"})
    assert exc_info.value.field == "alumni_id"


def test_sqlite_repo_create_alumni_duplicate_email_raises(sqlite_repo):
    """create_alumni() with an existing email must raise AlumniAlreadyExistsError."""
    with pytest.raises(AlumniAlreadyExistsError) as exc_info:
        # New alumni_id, but reuse alice@example.com which belongs to A001
        sqlite_repo.create_alumni({**_NEW_PROFILE, "email": "alice@example.com"})
    assert exc_info.value.field == "email"


# ---------------------------------------------------------------------------
# 6. create_alumni — CsvAlumniRepository (read-only guard)
# ---------------------------------------------------------------------------

def test_csv_repo_create_alumni_raises_not_implemented(csv_repo):
    """CsvAlumniRepository.create_alumni() must raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        csv_repo.create_alumni(_NEW_PROFILE)


# ---------------------------------------------------------------------------
# 7. update_alumni — SqliteAlumniRepository
# ---------------------------------------------------------------------------

_UPDATED_FIELDS = {
    "full_name": "Alice Smith-Jones",
    "email": "alice.updated@example.com",
    "skills": ["python", "ml"],
    "interests": ["coaching"],
    "location": "NY",
    "engagement_score": 0.90,
    "availability": "limited",
}


def test_sqlite_repo_update_alumni_returns_updated_dict(sqlite_repo):
    """update_alumni() must return a dict with all eight required keys."""
    result = sqlite_repo.update_alumni("A001", _UPDATED_FIELDS)
    assert isinstance(result, dict)
    required = {"alumni_id", "full_name", "email", "skills", "interests",
                "location", "engagement_score", "availability"}
    assert required.issubset(result.keys())
    assert result["alumni_id"] == "A001"
    assert result["full_name"] == _UPDATED_FIELDS["full_name"]


def test_sqlite_repo_update_alumni_persists_to_database(sqlite_repo, seeded_db):
    """update_alumni() must write the changes to the SQLite file."""
    sqlite_repo.update_alumni("A001", _UPDATED_FIELDS)

    con = sqlite3.connect(seeded_db)
    row = con.execute(
        "SELECT full_name, email FROM alumni WHERE alumni_id = ?", ("A001",)
    ).fetchone()
    con.close()

    assert row is not None
    assert row[0] == _UPDATED_FIELDS["full_name"]
    assert row[1] == _UPDATED_FIELDS["email"]


def test_sqlite_repo_update_alumni_updates_in_memory_cache_via_get_all(sqlite_repo):
    """After update_alumni(), get_all_alumni() must reflect the new values."""
    sqlite_repo.update_alumni("A001", _UPDATED_FIELDS)
    profiles = {p["alumni_id"]: p for p in sqlite_repo.get_all_alumni()}
    assert profiles["A001"]["full_name"] == _UPDATED_FIELDS["full_name"]


def test_sqlite_repo_update_alumni_findable_with_new_values_via_get_by_id(sqlite_repo):
    """After update_alumni(), get_alumni_by_id() must return the updated profile."""
    sqlite_repo.update_alumni("A001", _UPDATED_FIELDS)
    profile = sqlite_repo.get_alumni_by_id("A001")
    assert profile is not None
    assert profile["email"] == _UPDATED_FIELDS["email"]


def test_sqlite_repo_update_alumni_not_found_raises(sqlite_repo):
    """update_alumni() with a missing alumni_id must raise AlumniNotFoundError."""
    with pytest.raises(AlumniNotFoundError) as exc_info:
        sqlite_repo.update_alumni("DOES_NOT_EXIST", _UPDATED_FIELDS)
    assert exc_info.value.alumni_id == "DOES_NOT_EXIST"


def test_sqlite_repo_update_alumni_email_conflict_raises(sqlite_repo):
    """update_alumni() with another alumni's email must raise AlumniAlreadyExistsError."""
    with pytest.raises(AlumniAlreadyExistsError) as exc_info:
        # bob@example.com belongs to A002
        sqlite_repo.update_alumni("A001", {**_UPDATED_FIELDS, "email": "bob@example.com"})
    assert exc_info.value.field == "email"


def test_sqlite_repo_update_alumni_same_email_succeeds(sqlite_repo):
    """update_alumni() with the same email (no change) must not raise."""
    result = sqlite_repo.update_alumni("A001", {**_UPDATED_FIELDS, "email": "alice@example.com"})
    assert result["alumni_id"] == "A001"
    assert result["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# 8. update_alumni — CsvAlumniRepository (read-only guard)
# ---------------------------------------------------------------------------

def test_csv_repo_update_alumni_raises_not_implemented(csv_repo):
    """CsvAlumniRepository.update_alumni() must raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        csv_repo.update_alumni("A001", _UPDATED_FIELDS)
