"""
tests/test_api_key_management.py

Tests for Phase 2 key management endpoints — POST /v1/users (task 1).

All tests in this file are expected to fail with 404 until the endpoint
is implemented in src/api.py.

Covers:
    1. Valid username returns 201 with user_id and username
    2. Duplicate username returns 409
    3. Missing API key returns 401
    4. Wrong API key returns 401
    5. Empty username returns 422
    6. Whitespace-only username returns 422
    7. CSV/env-var mode returns 503
    8. Duplicate create does not insert a second user row
    9. Created user is persisted in the database

Strategy:
    - DB-mode tests monkeypatch DATABASE_PATH to a freshly seeded temp DB and
      use TestClient(app) as a context manager to trigger the lifespan.
    - CSV-mode test patches DATABASE_PATH to None (same pattern as
      test_api_db_auth.py fallback tests).
    - Each test gets its own seeded_db fixture instance for full isolation.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.api import app

VALID_KEY = {"x-api-key": "dev-secret-key"}


# ---------------------------------------------------------------------------
# Session hygiene — prevent rate-limit accumulation across modules
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="module")
def _reset_rate_limits():
    api_module._rate_limit_counts.clear()
    yield
    api_module._rate_limit_counts.clear()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path) -> str:
    """Return a freshly seeded temp database path (schema version 4)."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    return db_path


@pytest.fixture()
def db_client(seeded_db, monkeypatch):
    """TestClient in DB mode with lifespan triggered."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    with TestClient(app) as client:
        yield client, seeded_db


# ---------------------------------------------------------------------------
# 1. Valid username returns 201 with user_id and username
# ---------------------------------------------------------------------------

def test_create_user_returns_201_with_user_id_and_username(db_client):
    client, _ = db_client
    response = client.post("/v1/users", json={"username": "alice"}, headers=VALID_KEY)
    assert response.status_code == 201
    body = response.json()
    assert "user_id" in body
    assert body["username"] == "alice"
    assert len(body["user_id"]) == 36  # UUID — 32 hex + 4 hyphens


# ---------------------------------------------------------------------------
# 2. Duplicate username returns 409
# ---------------------------------------------------------------------------

def test_create_user_duplicate_username_returns_409(db_client):
    client, _ = db_client
    client.post("/v1/users", json={"username": "bob"}, headers=VALID_KEY)
    response = client.post("/v1/users", json={"username": "bob"}, headers=VALID_KEY)
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# 3. Missing API key returns 401
# ---------------------------------------------------------------------------

def test_create_user_missing_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.post("/v1/users", json={"username": "charlie"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. Wrong API key returns 401
# ---------------------------------------------------------------------------

def test_create_user_wrong_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.post(
        "/v1/users",
        json={"username": "dave"},
        headers={"x-api-key": "wrong-key"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 5. Empty username returns 422
# ---------------------------------------------------------------------------

def test_create_user_empty_username_returns_422(db_client):
    client, _ = db_client
    response = client.post("/v1/users", json={"username": ""}, headers=VALID_KEY)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 6. Whitespace-only username returns 422
# ---------------------------------------------------------------------------

def test_create_user_whitespace_only_username_returns_422(db_client):
    client, _ = db_client
    response = client.post("/v1/users", json={"username": "   "}, headers=VALID_KEY)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# 7. CSV/env-var mode returns 503
# ---------------------------------------------------------------------------

def test_create_user_csv_mode_returns_503(monkeypatch):
    """Without DATABASE_PATH the endpoint must signal it requires a DB deployment."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        response = client.post("/v1/users", json={"username": "eve"}, headers=VALID_KEY)
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 8. Duplicate create does not insert a second row
# ---------------------------------------------------------------------------

def test_create_user_duplicate_does_not_insert_second_row(db_client):
    """Second POST with the same username returns 409 and leaves exactly one DB row."""
    client, db_path = db_client
    client.post("/v1/users", json={"username": "frank"}, headers=VALID_KEY)
    client.post("/v1/users", json={"username": "frank"}, headers=VALID_KEY)

    con = sqlite3.connect(db_path)
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM users WHERE username = ?", ("frank",)
        ).fetchone()[0]
    finally:
        con.close()

    assert count == 1


# ---------------------------------------------------------------------------
# 9. Created user is persisted in the database
# ---------------------------------------------------------------------------

def test_create_user_persists_to_database(db_client):
    """After a 201 response the row must be readable directly from the DB."""
    client, db_path = db_client
    response = client.post("/v1/users", json={"username": "grace"}, headers=VALID_KEY)
    assert response.status_code == 201
    returned_user_id = response.json()["user_id"]

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT user_id, username FROM users WHERE username = ?", ("grace",)
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row[0] == returned_user_id
    assert row[1] == "grace"
