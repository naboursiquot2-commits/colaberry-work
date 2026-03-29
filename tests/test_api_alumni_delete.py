"""
tests/test_api_alumni_delete.py

Tests for DELETE /v1/alumni/{alumni_id} — the hard-delete endpoint.

Covers:
    1. Happy path: 204 with empty response body
    2. Authentication: 401 without key, 401 with wrong key
    3. Not found: 404 when alumni_id does not exist
    4. Visibility: deleted profile disappears from GET /v1/alumni/{id},
       GET /v1/alumni, and POST /v1/match
    5. Double delete: second DELETE on same ID returns 404
    6. CSV mode: 503 when DATABASE_PATH is None (read-only repository)

Strategy:
    - DB-mode tests use monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
      and TestClient(app) as a context manager to trigger lifespan.
    - Each test gets a fresh seeded_db via tmp_path — tests are fully isolated.
"""

import src.api as api_module
import pytest
from fastapi.testclient import TestClient

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.api import app

VALID_KEY = {"x-api-key": "dev-secret-key"}


# ---------------------------------------------------------------------------
# Session hygiene
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def _reset_rate_limits():
    """Clear the process-level rate-limit counters before and after this module.

    _rate_limit_counts is a module-level dict that persists across TestClient
    instances within a single pytest process. When many authenticated tests run
    before this module the "dev-secret-key" bucket can fill to >= 60 entries
    (the default RATE_LIMIT_MAX), causing all subsequent requests to return 429.
    Resetting at module entry and exit keeps each test module independent of
    accumulated counts from other modules, without touching the rate-limit logic
    or any existing test.
    """
    api_module._rate_limit_counts.clear()
    yield
    api_module._rate_limit_counts.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path) -> str:
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    return db_path


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

def test_delete_alumni_returns_204(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.delete("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 204


def test_delete_alumni_response_has_no_body(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.delete("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 204
    assert response.text == ""


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

def test_delete_alumni_requires_api_key(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.delete("/v1/alumni/A001")

    assert response.status_code == 401


def test_delete_alumni_wrong_api_key_returns_401(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.delete(
            "/v1/alumni/A001", headers={"x-api-key": "wrong-key"}
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. Not found (404)
# ---------------------------------------------------------------------------

def test_delete_alumni_not_found_returns_404(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.delete("/v1/alumni/DOES_NOT_EXIST", headers=VALID_KEY)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 4. Visibility after delete
# ---------------------------------------------------------------------------

def test_delete_alumni_removed_from_get_by_id(monkeypatch, seeded_db):
    """After DELETE, GET /v1/alumni/A001 must return 404."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.delete("/v1/alumni/A001", headers=VALID_KEY)
        response = client.get("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 404


def test_delete_alumni_removed_from_list(monkeypatch, seeded_db):
    """After DELETE, GET /v1/alumni must not contain the deleted profile."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.delete("/v1/alumni/A001", headers=VALID_KEY)
        response = client.get("/v1/alumni", headers=VALID_KEY)

    assert response.status_code == 200
    ids = [p["alumni_id"] for p in response.json()["results"]]
    assert "A001" not in ids


def test_delete_alumni_list_count_decreases(monkeypatch, seeded_db):
    """After DELETE, GET /v1/alumni count must be one less than before."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        before = client.get("/v1/alumni", headers=VALID_KEY).json()["count"]
        client.delete("/v1/alumni/A001", headers=VALID_KEY)
        after = client.get("/v1/alumni", headers=VALID_KEY).json()["count"]

    assert after == before - 1


def test_delete_alumni_removed_from_match_results(monkeypatch, seeded_db):
    """
    After deleting A003 (the only seeded alumnus with skill 'tableau'),
    POST /v1/match with skills=['tableau'] must return no results containing A003.

    A003 has skills ['sql','tableau'] — 'tableau' does not appear in any other
    seeded profile, so this confirms the deleted profile is gone from matching.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.delete("/v1/alumni/A003", headers=VALID_KEY)
        response = client.post(
            "/v1/match",
            headers=VALID_KEY,
            json={"skills": ["tableau"]},
        )

    assert response.status_code == 200
    ids = [r["alumni_id"] for r in response.json()["results"]]
    assert "A003" not in ids


# ---------------------------------------------------------------------------
# 5. Double delete
# ---------------------------------------------------------------------------

def test_delete_alumni_twice_returns_404_on_second(monkeypatch, seeded_db):
    """First DELETE must return 204; second DELETE of the same ID must return 404."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        first = client.delete("/v1/alumni/A001", headers=VALID_KEY)
        second = client.delete("/v1/alumni/A001", headers=VALID_KEY)

    assert first.status_code == 204
    assert second.status_code == 404


# ---------------------------------------------------------------------------
# 6. CSV mode (503)
# ---------------------------------------------------------------------------

def test_delete_alumni_returns_503_in_csv_mode(monkeypatch):
    """DELETE /v1/alumni/{id} must return 503 when DATABASE_PATH is None (CSV mode)."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)

    with TestClient(app) as client:
        response = client.delete("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 503
    assert "read-only" in response.json()["error"]["message"].lower()
