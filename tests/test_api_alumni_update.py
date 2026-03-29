"""
tests/test_api_alumni_update.py

Tests for PUT /v1/alumni/{alumni_id} — the full-replacement update endpoint.

Covers:
    1. Happy path: 200 with correct response body and normalized values
    2. Authentication: 401 without key, 401 with wrong key
    3. Validation: 422 for missing field, out-of-range score, whitespace strings,
       invalid email, and alumni_id in request body (forbidden by extra="forbid")
    4. Not-found: 404 when alumni_id does not exist
    5. Duplicate email: 409 when new email belongs to a different record
    6. Same email: 200 when email is unchanged (own-record update)
    7. Visibility: updated profile reflected in GET /v1/alumni, GET /v1/alumni/{id},
       and POST /v1/match
    8. CSV mode: 503 when DATABASE_PATH is None (read-only repository)

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

# The updated field values used across happy-path tests (targets A001 / Alice).
_UPDATED_FIELDS = {
    "full_name": "Alice Smith-Jones",
    "email": "alice.updated@example.com",
    "skills": ["python", "sql", "machine learning"],
    "interests": ["mentorship", "coaching"],
    "location": "NY",
    "engagement_score": 0.90,
    "availability": "limited",
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

def test_put_alumni_returns_200_with_valid_payload(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)

    assert response.status_code == 200


def test_put_alumni_response_body_has_all_required_fields(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)

    assert response.status_code == 200
    data = response.json()
    for field in ("alumni_id", "full_name", "email", "skills", "interests",
                  "location", "engagement_score", "availability"):
        assert field in data, f"Missing field: {field}"


def test_put_alumni_response_body_reflects_new_values(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)

    data = response.json()
    assert data["alumni_id"] == "A001"          # immutable — path value returned
    assert data["full_name"] == _UPDATED_FIELDS["full_name"]
    assert data["email"] == _UPDATED_FIELDS["email"]
    assert data["location"] == _UPDATED_FIELDS["location"]
    assert data["engagement_score"] == pytest.approx(_UPDATED_FIELDS["engagement_score"])
    assert data["availability"] == _UPDATED_FIELDS["availability"]


def test_put_alumni_skills_stored_lowercase(monkeypatch, seeded_db):
    """Skills sent in mixed case must be normalized to lowercase."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "skills": ["Python", "  SQL  "]}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 200
    assert response.json()["skills"] == ["python", "sql"]


def test_put_alumni_alumni_id_in_response_matches_path_not_any_body_value(
    monkeypatch, seeded_db
):
    """The returned alumni_id must always be the path parameter value."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)

    assert response.json()["alumni_id"] == "A001"


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

def test_put_alumni_requires_api_key(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", json=_UPDATED_FIELDS)

    assert response.status_code == 401


def test_put_alumni_wrong_api_key_returns_401(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put(
            "/v1/alumni/A001",
            headers={"x-api-key": "wrong-key"},
            json=_UPDATED_FIELDS,
        )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. Validation (422)
# ---------------------------------------------------------------------------

def test_put_alumni_body_containing_alumni_id_returns_422(monkeypatch, seeded_db):
    """alumni_id is forbidden in the request body (extra='forbid')."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "alumni_id": "A001"}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_put_alumni_missing_required_field_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {k: v for k, v in _UPDATED_FIELDS.items() if k != "full_name"}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == 422


def test_put_alumni_engagement_score_above_one_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "engagement_score": 1.5}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_put_alumni_engagement_score_below_zero_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "engagement_score": -0.1}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_put_alumni_whitespace_only_full_name_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "full_name": "   "}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_put_alumni_invalid_email_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "email": "not-an-email"}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


def test_put_alumni_empty_skill_item_returns_422(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "skills": ["python", "  "]}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 4. Not-found (404)
# ---------------------------------------------------------------------------

def test_put_alumni_not_found_returns_404(monkeypatch, seeded_db):
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        response = client.put(
            "/v1/alumni/DOES_NOT_EXIST", headers=VALID_KEY, json=_UPDATED_FIELDS
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == 404


# ---------------------------------------------------------------------------
# 5. Duplicate email (409)
# ---------------------------------------------------------------------------

def test_put_alumni_email_conflict_returns_409(monkeypatch, seeded_db):
    """Updating A001 with bob@example.com (A002's email) must return 409."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "email": "bob@example.com"}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 409
    assert "email" in response.json()["error"]["message"]


# ---------------------------------------------------------------------------
# 6. Same email allowed
# ---------------------------------------------------------------------------

def test_put_alumni_same_email_update_succeeds(monkeypatch, seeded_db):
    """Updating a profile while keeping the same email must return 200."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    # Keep alice's email unchanged, only update full_name
    payload = {**_UPDATED_FIELDS, "email": "alice@example.com"}

    with TestClient(app) as client:
        response = client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"


# ---------------------------------------------------------------------------
# 7. Visibility after update
# ---------------------------------------------------------------------------

def test_put_alumni_updated_profile_reflected_in_get_by_id(monkeypatch, seeded_db):
    """After PUT, GET /v1/alumni/A001 must return the new values."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)
        response = client.get("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == _UPDATED_FIELDS["full_name"]
    assert data["email"] == _UPDATED_FIELDS["email"]


def test_put_alumni_updated_profile_reflected_in_list(monkeypatch, seeded_db):
    """After PUT, GET /v1/alumni must contain the updated values for A001."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)

    with TestClient(app) as client:
        client.put("/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS)
        response = client.get("/v1/alumni", headers=VALID_KEY)

    profiles = {p["alumni_id"]: p for p in response.json()["results"]}
    assert profiles["A001"]["full_name"] == _UPDATED_FIELDS["full_name"]


def test_put_alumni_updated_skills_appear_in_match_results(monkeypatch, seeded_db):
    """
    After updating A001 with a unique skill ('cobol'), POST /v1/match with
    skills=['cobol'] must return A001 as the top result.
    'cobol' is not present in any seeded profile, so A001 is the only match.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    payload = {**_UPDATED_FIELDS, "skills": ["cobol"]}

    with TestClient(app) as client:
        client.put("/v1/alumni/A001", headers=VALID_KEY, json=payload)
        response = client.post(
            "/v1/match",
            headers=VALID_KEY,
            json={"skills": ["cobol"]},
        )

    assert response.status_code == 200
    ids = [r["alumni_id"] for r in response.json()["results"]]
    assert "A001" in ids
    # A001 must be ranked first since it is the only profile with 'cobol'
    assert ids[0] == "A001"


# ---------------------------------------------------------------------------
# 8. CSV mode (503)
# ---------------------------------------------------------------------------

def test_put_alumni_returns_503_in_csv_mode(monkeypatch):
    """PUT /v1/alumni/{id} must return 503 when DATABASE_PATH is None (CSV mode)."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)

    with TestClient(app) as client:
        response = client.put(
            "/v1/alumni/A001", headers=VALID_KEY, json=_UPDATED_FIELDS
        )

    assert response.status_code == 503
    assert "read-only" in response.json()["error"]["message"].lower()
