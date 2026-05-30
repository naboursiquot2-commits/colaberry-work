"""
tests/test_api_key_management.py

Tests for Phase 2 key management endpoints.

Task 1 — POST /v1/users:
    1.  Valid username returns 201 with user_id and username
    2.  Duplicate username returns 409
    3.  Missing API key returns 401
    4.  Wrong API key returns 401
    5.  Empty username returns 422
    6.  Whitespace-only username returns 422
    7.  CSV/env-var mode returns 503
    8.  Duplicate create does not insert a second user row
    9.  Created user is persisted in the database

Task 2 — POST /v1/users/{user_id}/keys:
    10. Valid user_id returns 201 with key_id, key_prefix, and raw_key
    11. raw_key has the expected {prefix}.{secret} format and prefix matches key_prefix
    12. Created key is persisted as a hash, not plaintext
    13. Missing API key returns 401
    14. Wrong API key returns 401
    15. Nonexistent user_id returns 404
    16. CSV/env-var mode returns 503
    17. Optional description is persisted to the database
    18. Optional expires_at is persisted to the database
    19. Generated raw_key can authenticate successfully against a protected endpoint

Task 3 — DELETE /v1/keys/{key_id}:
    20. Revoke existing key returns 204
    21. Revoked key can no longer authenticate
    22. Nonexistent key_id returns 404
    23. Missing API key returns 401
    24. Wrong API key returns 401
    25. CSV/env-var mode returns 503
    26. Revocation is persisted in the database (is_active = 0)
    27. Second revoke of same key returns 404
    28. Revoking one key does not affect another key owned by the same user

Task 4 — GET /v1/keys:
    29. Authenticated user receives a list of their active keys
    30. Revoked keys are excluded from the list
    31. Keys belonging to other users are excluded
    32. A user with all keys revoked cannot access GET /v1/keys (401) —
        this is the closest testable proxy for "empty list": a user with
        zero active keys cannot authenticate to call the endpoint
    33. Missing API key returns 401
    34. Wrong API key returns 401
    35. CSV/env-var mode returns 503
    36. raw_key is never present in any list entry
    37. key_hash is never present in any list entry
    38. description is present and correct
    39. expires_at is present and correct
    40. last_used_at is returned and populated after the key is used

Strategy:
    - DB-mode tests monkeypatch DATABASE_PATH to a freshly seeded temp DB and
      use TestClient(app) as a context manager to trigger the lifespan.
    - CSV-mode tests patch DATABASE_PATH to None.
    - Each test gets its own seeded_db fixture instance for full isolation.
    - Task 2 tests use the created_user fixture (POST /v1/users already implemented).
    - Task 3 tests use the created_key fixture (POST /v1/users/{user_id}/keys already
      implemented) which depends on created_user.
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


# ===========================================================================
# Task 2 — POST /v1/users/{user_id}/keys
# ===========================================================================

@pytest.fixture()
def created_user(db_client):
    """Create a user via POST /v1/users and return (client, db_path, user_id)."""
    client, db_path = db_client
    resp = client.post("/v1/users", json={"username": "keytest"}, headers=VALID_KEY)
    assert resp.status_code == 201, f"created_user fixture: expected 201, got {resp.status_code}"
    return client, db_path, resp.json()["user_id"]


# ---------------------------------------------------------------------------
# 10. Valid user_id returns 201 with key_id, key_prefix, and raw_key
# ---------------------------------------------------------------------------

def test_create_key_returns_201_with_key_id_prefix_and_raw_key(created_user):
    client, _, user_id = created_user
    response = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert response.status_code == 201
    body = response.json()
    assert "key_id" in body
    assert "key_prefix" in body
    assert "raw_key" in body


# ---------------------------------------------------------------------------
# 11. raw_key has the expected format and prefix matches key_prefix
# ---------------------------------------------------------------------------

def test_create_key_raw_key_has_expected_format(created_user):
    """raw_key must be {8-char prefix}.{56-char secret} (65 chars total)."""
    client, _, user_id = created_user
    response = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert response.status_code == 201
    body = response.json()
    raw_key = body["raw_key"]

    assert len(raw_key) == 65
    assert raw_key.count(".") == 1
    prefix, secret = raw_key.split(".", 1)
    assert len(prefix) == 8
    assert len(secret) == 56
    assert prefix == body["key_prefix"]


# ---------------------------------------------------------------------------
# 12. Created key is persisted as a hash, not plaintext
# ---------------------------------------------------------------------------

def test_create_key_stored_as_hash_not_plaintext(created_user):
    """key_hash in the DB must not contain the raw_key; must follow salt:digest format."""
    client, db_path, user_id = created_user
    response = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert response.status_code == 201
    body = response.json()
    raw_key = body["raw_key"]
    key_id = body["key_id"]

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT key_hash, is_active FROM api_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    key_hash, is_active = row
    assert raw_key not in key_hash       # plaintext must not appear in stored value
    assert ":" in key_hash               # salt:digest separator
    assert is_active == 1


# ---------------------------------------------------------------------------
# 13. Missing API key returns 401
# ---------------------------------------------------------------------------

def test_create_key_missing_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.post("/v1/users/some-user-id/keys", json={})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 14. Wrong API key returns 401
# ---------------------------------------------------------------------------

def test_create_key_wrong_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.post(
        "/v1/users/some-user-id/keys",
        json={},
        headers={"x-api-key": "wrong-key"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 15. Nonexistent user_id returns 404
# ---------------------------------------------------------------------------

def test_create_key_nonexistent_user_id_returns_404(db_client):
    client, _ = db_client
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.post(f"/v1/users/{fake_id}/keys", json={}, headers=VALID_KEY)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 16. CSV/env-var mode returns 503
# ---------------------------------------------------------------------------

def test_create_key_csv_mode_returns_503(monkeypatch):
    """Without a DB-backed deployment the keys endpoint must return 503."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    fake_id = "00000000-0000-0000-0000-000000000000"
    with TestClient(app) as client:
        response = client.post(
            f"/v1/users/{fake_id}/keys", json={}, headers=VALID_KEY
        )
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 17. Optional description is persisted
# ---------------------------------------------------------------------------

def test_create_key_description_is_persisted(created_user):
    client, db_path, user_id = created_user
    response = client.post(
        f"/v1/users/{user_id}/keys",
        json={"description": "CI smoke-test key"},
        headers=VALID_KEY,
    )
    assert response.status_code == 201
    key_id = response.json()["key_id"]

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT description FROM api_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row[0] == "CI smoke-test key"


# ---------------------------------------------------------------------------
# 18. Optional expires_at is persisted
# ---------------------------------------------------------------------------

def test_create_key_expires_at_is_persisted(created_user):
    client, db_path, user_id = created_user
    expires = "2030-01-01 00:00:00"
    response = client.post(
        f"/v1/users/{user_id}/keys",
        json={"expires_at": expires},
        headers=VALID_KEY,
    )
    assert response.status_code == 201
    key_id = response.json()["key_id"]

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT expires_at FROM api_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row[0] == expires


# ---------------------------------------------------------------------------
# 19. Generated raw_key authenticates successfully
# ---------------------------------------------------------------------------

def test_create_key_raw_key_authenticates_successfully(created_user):
    """A key returned by the endpoint must pass _require_api_key on a protected route."""
    client, _, user_id = created_user
    response = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert response.status_code == 201
    raw_key = response.json()["raw_key"]

    auth_response = client.get("/v1/alumni", headers={"x-api-key": raw_key})
    assert auth_response.status_code == 200


# ===========================================================================
# Task 3 — DELETE /v1/keys/{key_id}
# ===========================================================================

@pytest.fixture()
def created_key(created_user):
    """Issue a key for the keytest user; return (client, db_path, user_id, key_id, raw_key)."""
    client, db_path, user_id = created_user
    resp = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert resp.status_code == 201, f"created_key fixture: expected 201, got {resp.status_code}"
    body = resp.json()
    return client, db_path, user_id, body["key_id"], body["raw_key"]


# ---------------------------------------------------------------------------
# 20. Revoke existing key returns 204
# ---------------------------------------------------------------------------

def test_revoke_key_returns_204(created_key):
    client, _, _, key_id, _ = created_key
    response = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert response.status_code == 204


# ---------------------------------------------------------------------------
# 21. Revoked key can no longer authenticate
# ---------------------------------------------------------------------------

def test_revoke_key_prevents_authentication(created_key):
    client, _, _, key_id, raw_key = created_key
    revoke = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert revoke.status_code == 204
    auth = client.get("/v1/alumni", headers={"x-api-key": raw_key})
    assert auth.status_code == 401


# ---------------------------------------------------------------------------
# 22. Nonexistent key_id returns 404
# ---------------------------------------------------------------------------

def test_revoke_key_nonexistent_key_id_returns_404(db_client):
    client, _ = db_client
    fake_id = "00000000-0000-0000-0000-000000000000"
    response = client.delete(f"/v1/keys/{fake_id}", headers=VALID_KEY)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 23. Missing API key returns 401
# ---------------------------------------------------------------------------

def test_revoke_key_missing_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.delete("/v1/keys/some-key-id")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 24. Wrong API key returns 401
# ---------------------------------------------------------------------------

def test_revoke_key_wrong_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.delete(
        "/v1/keys/some-key-id",
        headers={"x-api-key": "wrong-key"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 25. CSV mode returns 503
# ---------------------------------------------------------------------------

def test_revoke_key_csv_mode_returns_503(monkeypatch):
    """Without a DB-backed deployment the revoke endpoint must return 503."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    fake_id = "00000000-0000-0000-0000-000000000000"
    with TestClient(app) as client:
        response = client.delete(f"/v1/keys/{fake_id}", headers=VALID_KEY)
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 26. Revocation is persisted in the database
# ---------------------------------------------------------------------------

def test_revoke_key_sets_is_active_to_0_in_database(created_key):
    client, db_path, _, key_id, _ = created_key
    revoke = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert revoke.status_code == 204

    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT is_active FROM api_keys WHERE key_id = ?", (key_id,)
        ).fetchone()
    finally:
        con.close()

    assert row is not None
    assert row[0] == 0


# ---------------------------------------------------------------------------
# 27. Second revoke of same key returns 404
# ---------------------------------------------------------------------------

def test_revoke_key_second_revoke_returns_404(created_key):
    client, _, _, key_id, _ = created_key
    first = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert first.status_code == 204
    second = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert second.status_code == 404


# ---------------------------------------------------------------------------
# 28. Revoking one key does not affect another key owned by the same user
# ---------------------------------------------------------------------------

def test_revoke_key_does_not_affect_sibling_key(created_user):
    """Revoke key_1; key_2 belonging to the same user must still authenticate."""
    client, _, user_id = created_user
    resp1 = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    resp2 = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    key_id_1 = resp1.json()["key_id"]
    raw_key_2 = resp2.json()["raw_key"]

    revoke = client.delete(f"/v1/keys/{key_id_1}", headers=VALID_KEY)
    assert revoke.status_code == 204

    auth = client.get("/v1/alumni", headers={"x-api-key": raw_key_2})
    assert auth.status_code == 200


# ===========================================================================
# Task 4 — GET /v1/keys
# ===========================================================================

# ---------------------------------------------------------------------------
# 29. Authenticated user receives a list of their active keys
# ---------------------------------------------------------------------------

def test_get_keys_returns_list_of_active_keys(created_key):
    client, _, _, key_id, raw_key = created_key
    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert key_id in [k["key_id"] for k in body]


# ---------------------------------------------------------------------------
# 30. Revoked keys are excluded from the list
# ---------------------------------------------------------------------------

def test_get_keys_excludes_revoked_keys(created_user):
    client, _, user_id = created_user
    r1 = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    r2 = client.post(f"/v1/users/{user_id}/keys", json={}, headers=VALID_KEY)
    assert r1.status_code == 201
    assert r2.status_code == 201
    key_id_1 = r1.json()["key_id"]
    raw_key_2 = r2.json()["raw_key"]

    revoke = client.delete(f"/v1/keys/{key_id_1}", headers=VALID_KEY)
    assert revoke.status_code == 204

    response = client.get("/v1/keys", headers={"x-api-key": raw_key_2})
    assert response.status_code == 200
    assert key_id_1 not in [k["key_id"] for k in response.json()]


# ---------------------------------------------------------------------------
# 31. Keys belonging to other users are excluded
# ---------------------------------------------------------------------------

def test_get_keys_excludes_keys_from_other_users(db_client):
    client, _ = db_client
    ua = client.post("/v1/users", json={"username": "usera"}, headers=VALID_KEY)
    ub = client.post("/v1/users", json={"username": "userb"}, headers=VALID_KEY)
    assert ua.status_code == 201
    assert ub.status_code == 201

    ka = client.post(f"/v1/users/{ua.json()['user_id']}/keys", json={}, headers=VALID_KEY)
    kb = client.post(f"/v1/users/{ub.json()['user_id']}/keys", json={}, headers=VALID_KEY)
    assert ka.status_code == 201
    assert kb.status_code == 201

    response = client.get("/v1/keys", headers={"x-api-key": ka.json()["raw_key"]})
    assert response.status_code == 200
    assert kb.json()["key_id"] not in [k["key_id"] for k in response.json()]


# ---------------------------------------------------------------------------
# 32. Revoked key returns 401 — closest testable proxy for "empty list"
# ---------------------------------------------------------------------------

def test_get_keys_revoked_key_returns_401(created_key):
    """
    A user with all keys revoked cannot authenticate to call GET /v1/keys.
    This is the closest testable proxy for 'empty list': once the user's only
    active key is revoked, the endpoint returns 401 rather than an empty list.
    Testing a literal [] response would require authenticating as a user with
    zero active keys, which is impossible by design.
    """
    client, _, _, key_id, raw_key = created_key
    revoke = client.delete(f"/v1/keys/{key_id}", headers=VALID_KEY)
    assert revoke.status_code == 204

    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 33. Missing API key returns 401
# ---------------------------------------------------------------------------

def test_get_keys_missing_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.get("/v1/keys")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 34. Wrong API key returns 401
# ---------------------------------------------------------------------------

def test_get_keys_wrong_api_key_returns_401(db_client):
    client, _ = db_client
    response = client.get("/v1/keys", headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 35. CSV mode returns 503
# ---------------------------------------------------------------------------

def test_get_keys_csv_mode_returns_503(monkeypatch):
    """Without a DB-backed deployment the list endpoint must return 503."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        response = client.get("/v1/keys", headers=VALID_KEY)
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# 36. raw_key is never present in any list entry
# ---------------------------------------------------------------------------

def test_get_keys_response_does_not_include_raw_key(created_key):
    client, _, _, _, raw_key = created_key
    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    for entry in response.json():
        assert "raw_key" not in entry


# ---------------------------------------------------------------------------
# 37. key_hash is never present in any list entry
# ---------------------------------------------------------------------------

def test_get_keys_response_does_not_include_key_hash(created_key):
    client, _, _, _, raw_key = created_key
    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    for entry in response.json():
        assert "key_hash" not in entry


# ---------------------------------------------------------------------------
# 38. description is present and correct
# ---------------------------------------------------------------------------

def test_get_keys_description_is_returned(created_user):
    client, _, user_id = created_user
    resp = client.post(
        f"/v1/users/{user_id}/keys",
        json={"description": "my ci key"},
        headers=VALID_KEY,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["raw_key"]
    key_id = resp.json()["key_id"]

    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    entry = next((k for k in response.json() if k["key_id"] == key_id), None)
    assert entry is not None
    assert entry["description"] == "my ci key"


# ---------------------------------------------------------------------------
# 39. expires_at is present and correct
# ---------------------------------------------------------------------------

def test_get_keys_expires_at_is_returned(created_user):
    client, _, user_id = created_user
    expires = "2030-06-01 00:00:00"
    resp = client.post(
        f"/v1/users/{user_id}/keys",
        json={"expires_at": expires},
        headers=VALID_KEY,
    )
    assert resp.status_code == 201
    raw_key = resp.json()["raw_key"]
    key_id = resp.json()["key_id"]

    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    entry = next((k for k in response.json() if k["key_id"] == key_id), None)
    assert entry is not None
    assert entry["expires_at"] == expires


# ---------------------------------------------------------------------------
# 40. last_used_at is returned and populated after the key is used
# ---------------------------------------------------------------------------

def test_get_keys_last_used_at_is_returned(created_key):
    """
    verify_key() sets last_used_at on every successful auth. The GET /v1/keys
    request itself authenticates via _require_api_key, which calls verify_key()
    before the route handler runs, so last_used_at is non-null in the response.
    """
    client, _, _, key_id, raw_key = created_key
    response = client.get("/v1/keys", headers={"x-api-key": raw_key})
    assert response.status_code == 200
    entry = next((k for k in response.json() if k["key_id"] == key_id), None)
    assert entry is not None
    assert entry["last_used_at"] is not None
