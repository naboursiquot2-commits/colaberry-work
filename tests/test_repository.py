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

import pytest

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.repository import AlumniRepository, CsvAlumniRepository, SqliteAlumniRepository


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
