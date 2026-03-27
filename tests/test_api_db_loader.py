"""
tests/test_api_db_loader.py

Tests for the DATABASE_PATH loader selection introduced in src/api.py.

Covers:
    1. Default behavior: DATABASE_PATH unset → CSV loader used
    2. DATABASE_PATH set to a valid seeded DB → DB loader used
    3. DATABASE_PATH set but file does not exist → falls back to CSV
    4. API responses and match ranking are identical under DB mode

Strategy:
    The loader selection happens inside the lifespan context manager at
    app startup. To exercise both paths in tests:
    - Patch src.api.DATABASE_PATH to the desired value
    - Instantiate TestClient(app) as a context manager (triggers lifespan)
    - Assert on the resulting app.state.profiles and API responses

All tests use a temporary seeded SQLite database (tmp_path + seed()).
The real data/alumni.db is never touched.
"""

import src.api as api_module
from fastapi.testclient import TestClient

import pytest

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.api import app
from src.matching_engine import load_alumni_profiles_csv

VALID_KEY = {"x-api-key": "dev-secret-key"}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path) -> str:
    """Return the path of a freshly seeded temporary SQLite database."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    return db_path


# ---------------------------------------------------------------------------
# 1. Default behavior: no DATABASE_PATH → CSV loader
# ---------------------------------------------------------------------------

def test_default_loads_from_csv_when_database_path_unset(monkeypatch):
    """
    When DATABASE_PATH is None (the default), the lifespan must load profiles
    from the CSV file. The profile count must match the CSV row count.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["profiles_loaded"] == len(load_alumni_profiles_csv(DEFAULT_CSV_PATH))


def test_default_loads_from_csv_when_database_path_missing_file(monkeypatch, tmp_path):
    """
    When DATABASE_PATH points to a file that does not exist, the lifespan
    must fall back to the CSV loader rather than raising an error.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", str(tmp_path / "no_such.db"))

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["profiles_loaded"] == len(load_alumni_profiles_csv(DEFAULT_CSV_PATH))


# ---------------------------------------------------------------------------
# 2. DB path: DATABASE_PATH set to a valid seeded DB → DB loader used
# ---------------------------------------------------------------------------

def test_db_path_loads_from_database_when_set(monkeypatch, seeded_db):
    """
    When DATABASE_PATH points to an existing seeded database, the lifespan
    must load profiles from SQLite. The profile count must match.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["profiles_loaded"] == 6


def test_db_path_profiles_stored_in_app_state(monkeypatch, seeded_db):
    """
    After startup with DATABASE_PATH set, app.state.profiles must be a
    non-empty list of dicts with the expected profile keys.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        profiles = app.state.profiles

    assert isinstance(profiles, list)
    assert len(profiles) == 6
    for profile in profiles:
        assert "alumni_id" in profile
        assert "skills" in profile
        assert isinstance(profile["skills"], list)


# ---------------------------------------------------------------------------
# 3. API endpoints behave identically under DB mode
# ---------------------------------------------------------------------------

def test_health_returns_ok_under_db_mode(monkeypatch, seeded_db):
    """/v1/health must return 200 with status 'ok' when DB loader is active."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_match_returns_200_under_db_mode(monkeypatch, seeded_db):
    """/v1/match must return 200 with ranked results when DB loader is active."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post(
            "/v1/match",
            headers=VALID_KEY,
            json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) > 0


def test_alumni_listing_returns_200_under_db_mode(monkeypatch, seeded_db):
    """/v1/alumni must return 200 with profile list when DB loader is active."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.get("/v1/alumni", headers=VALID_KEY)

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["results"], list)
    assert data["count"] == 6


def test_alumni_by_id_returns_200_under_db_mode(monkeypatch, seeded_db):
    """/v1/alumni/A001 must return the correct profile when DB loader is active."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.get("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 200
    assert response.json()["alumni_id"] == "A001"


def test_auth_still_required_under_db_mode(monkeypatch, seeded_db):
    """Authentication must still be enforced when DB loader is active."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post(
            "/v1/match",
            json={"skills": ["python"]},
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. Match ranking is identical under CSV and DB modes
# ---------------------------------------------------------------------------

def test_match_ranking_order_identical_under_csv_and_db(monkeypatch, seeded_db):
    """
    The alumni_id ranking order returned by /v1/match must be the same
    whether the app loaded profiles from CSV or from the DB.
    """
    request_body = {
        "skills": ["python", "sql"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    # CSV mode
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        csv_response = client.post("/v1/match", headers=VALID_KEY, json=request_body)

    # DB mode
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    with TestClient(app) as client:
        db_response = client.post("/v1/match", headers=VALID_KEY, json=request_body)

    csv_order = [r["alumni_id"] for r in csv_response.json()["results"]]
    db_order = [r["alumni_id"] for r in db_response.json()["results"]]

    assert csv_order == db_order, (
        f"Ranking order differs between loaders.\n"
        f"  CSV: {csv_order}\n"
        f"  DB:  {db_order}"
    )


def test_match_scores_identical_under_csv_and_db(monkeypatch, seeded_db):
    """
    total_score for every alumni_id must be identical (within float tolerance)
    under CSV and DB loader modes.
    """
    request_body = {
        "skills": ["python", "sql"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        csv_results = client.post("/v1/match", headers=VALID_KEY, json=request_body).json()["results"]

    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    with TestClient(app) as client:
        db_results = client.post("/v1/match", headers=VALID_KEY, json=request_body).json()["results"]

    csv_scores = {r["alumni_id"]: r["total_score"] for r in csv_results}
    db_scores = {r["alumni_id"]: r["total_score"] for r in db_results}

    for alumni_id, csv_score in csv_scores.items():
        assert db_scores[alumni_id] == pytest.approx(csv_score), (
            f"{alumni_id}: CSV score {csv_score} != DB score {db_scores[alumni_id]}"
        )
