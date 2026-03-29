"""
tests/test_api_alumni_create.py

Tests for POST /v1/alumni — the first write-capable API endpoint.

Covers:
    1. Happy path: 201 with correct response body
    2. Authentication: 401 without key, 401 with wrong key
    3. Validation: 422 for missing field, out-of-range score, empty strings, bad email
    4. Duplicate handling: 409 for duplicate alumni_id, 409 for duplicate email
    5. Visibility: created profile appears in GET /v1/alumni and GET /v1/alumni/{id}
    6. Matching: created profile participates in POST /v1/match results
    7. CSV mode: 503 when DATABASE_PATH is unset (read-only repository)

Strategy:
    - DB-mode tests use monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
      and TestClient(app) as a context manager to trigger lifespan.
    - The seeded_db fixture creates a fresh temporary SQLite database for each test
      so tests are fully isolated.
    - CSV-mode tests use monkeypatch to ensure DATABASE_PATH is None.
"""

import src.api as api_module
import pytest
from fastapi.testclient import TestClient

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.api import app

VALID_KEY = {"x-api-key": "dev-secret-key"}

_NEW_ALUMNI = {
    "alumni_id": "A007",
    "full_name": "Grace Hopper",
    "email": "grace.hopper@example.com",
    "skills": ["python", "fortran"],
    "interests": ["mentorship", "education"],
    "location": "NY",
    "engagement_score": 0.85,
    "availability": "available",
}


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

def test_post_alumni_returns_201_with_valid_payload(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)

    assert response.status_code == 201


def test_post_alumni_response_body_has_all_required_fields(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)

    assert response.status_code == 201
    data = response.json()
    for field in ("alumni_id", "full_name", "email", "skills", "interests",
                  "location", "engagement_score", "availability"):
        assert field in data, f"Missing field: {field}"


def test_post_alumni_response_body_matches_input(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)

    data = response.json()
    assert data["alumni_id"] == _NEW_ALUMNI["alumni_id"]
    assert data["full_name"] == _NEW_ALUMNI["full_name"]
    assert data["email"] == _NEW_ALUMNI["email"]
    assert data["location"] == _NEW_ALUMNI["location"]
    assert data["engagement_score"] == pytest.approx(_NEW_ALUMNI["engagement_score"])
    assert data["availability"] == _NEW_ALUMNI["availability"]


def test_post_alumni_skills_stored_lowercase(monkeypatch, seeded_db):
    """Skills sent in mixed case must be stored and returned lowercase."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "skills": ["Python", "  Fortran  "]}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 201
    assert response.json()["skills"] == ["python", "fortran"]


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

def test_post_alumni_requires_api_key(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post("/v1/alumni", json=_NEW_ALUMNI)

    assert response.status_code == 401


def test_post_alumni_wrong_api_key_returns_401(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.post(
            "/v1/alumni",
            headers={"x-api-key": "wrong-key"},
            json=_NEW_ALUMNI,
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. Validation (422)
# ---------------------------------------------------------------------------

def test_post_alumni_missing_required_field_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {k: v for k, v in _NEW_ALUMNI.items() if k != "alumni_id"}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == 422


def test_post_alumni_engagement_score_above_one_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "engagement_score": 1.5}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_post_alumni_engagement_score_below_zero_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "engagement_score": -0.1}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_post_alumni_whitespace_only_alumni_id_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "alumni_id": "   "}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_post_alumni_invalid_email_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "email": "not-an-email"}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_post_alumni_empty_skill_item_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "skills": ["python", "  "]}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. Duplicate handling (409)
# ---------------------------------------------------------------------------

def test_post_alumni_duplicate_id_returns_409(monkeypatch, seeded_db):
    """Posting with an alumni_id that already exists must return 409."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_NEW_ALUMNI, "alumni_id": "A001"}  # A001 already exists in seed

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 409
    assert "alumni_id" in response.json()["error"]["message"]


def test_post_alumni_duplicate_email_returns_409(monkeypatch, seeded_db):
    """Posting with an email that already exists must return 409."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    # New alumni_id but reuse alice@example.com which belongs to A001
    payload = {**_NEW_ALUMNI, "email": "alice@example.com"}

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=payload)

    assert response.status_code == 409
    assert "email" in response.json()["error"]["message"]


def test_post_alumni_first_call_succeeds_second_duplicate_returns_409(monkeypatch, seeded_db):
    """First POST succeeds with 201; second POST with same alumni_id returns 409."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        r1 = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)
        r2 = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)

    assert r1.status_code == 201
    assert r2.status_code == 409


# ---------------------------------------------------------------------------
# 5. Visibility after creation
# ---------------------------------------------------------------------------

def test_post_alumni_appears_in_list_alumni(monkeypatch, seeded_db):
    """After creation, GET /v1/alumni must include the new alumni_id."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)
        response = client.get("/v1/alumni", headers=VALID_KEY)

    ids = [p["alumni_id"] for p in response.json()["results"]]
    assert _NEW_ALUMNI["alumni_id"] in ids


def test_post_alumni_retrievable_by_get_alumni_by_id(monkeypatch, seeded_db):
    """After creation, GET /v1/alumni/{alumni_id} must return the new profile."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)
        response = client.get(f"/v1/alumni/{_NEW_ALUMNI['alumni_id']}", headers=VALID_KEY)

    assert response.status_code == 200
    assert response.json()["alumni_id"] == _NEW_ALUMNI["alumni_id"]


# ---------------------------------------------------------------------------
# 6. Matching participation
# ---------------------------------------------------------------------------

def test_post_alumni_new_profile_appears_in_match_results(monkeypatch, seeded_db):
    """
    After creation, POST /v1/match must rank the new alumni when their
    unique skill is in the request. Uses 'fortran' — not present in any
    seeded profile — to ensure the new alumni is the only match.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)
        response = client.post(
            "/v1/match",
            headers=VALID_KEY,
            json={"skills": ["fortran"]},
        )

    assert response.status_code == 200
    ids = [r["alumni_id"] for r in response.json()["results"]]
    assert _NEW_ALUMNI["alumni_id"] in ids


# ---------------------------------------------------------------------------
# 7. CSV mode — 503
# ---------------------------------------------------------------------------

def test_post_alumni_returns_503_in_csv_mode(monkeypatch):
    """POST /v1/alumni must return 503 when DATABASE_PATH is None (CSV mode)."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)

    with TestClient(app) as client:
        response = client.post("/v1/alumni", headers=VALID_KEY, json=_NEW_ALUMNI)

    assert response.status_code == 503
    assert "read-only" in response.json()["error"]["message"].lower()
