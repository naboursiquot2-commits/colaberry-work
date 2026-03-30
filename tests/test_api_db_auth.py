"""
tests/test_api_db_auth.py

Integration tests for Phase 1 database-backed API key authentication.

Covers:
    1. DB mode — valid key authenticates successfully (200)
    2. DB mode — wrong secret returns 401
    3. DB mode — completely unknown key returns 401
    4. DB mode — missing x-api-key header returns 401
    5. DB mode — revoked key returns 401 after revocation
    6. DB mode — rate-limit bucket is the key_id (UUID), not the raw value
    7. Env-var fallback (CSV mode) — original API_KEY value still works
    8. Env-var fallback (CSV mode) — wrong key returns 401
    9. Bootstrap — lifespan seeds the API_KEY env-var into the DB as a hashed row
   10. Bootstrap — running lifespan twice does not create duplicate rows

Strategy:
    - DB-mode tests patch DATABASE_PATH to a freshly seeded temp DB and use
      TestClient(app) as a context manager to trigger the lifespan.
    - CSV-mode fallback tests patch DATABASE_PATH to None.
    - The rate-limit dict is cleared before and after this module to prevent
      accumulation from other test modules affecting these tests.
"""

import sqlite3

import src.api as api_module
import pytest
from fastapi.testclient import TestClient

from execution.seed_database import DEFAULT_CSV_PATH, seed
from src.api import app
from src.api_key_repository import ApiKeyRepository

VALID_KEY = {"x-api-key": "dev-secret-key"}


# ---------------------------------------------------------------------------
# Session hygiene — prevent rate-limit accumulation from other modules
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
    """
    TestClient in DB mode with lifespan triggered.

    The lifespan bootstrap seeds 'dev-secret-key' as a hashed row, so
    VALID_KEY headers work against the DB-backed auth path.
    """
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    with TestClient(app) as client:
        yield client, seeded_db


# ---------------------------------------------------------------------------
# 1. Valid key authenticates (200)
# ---------------------------------------------------------------------------

def test_db_mode_valid_key_returns_200(db_client):
    client, _ = db_client
    response = client.get("/v1/alumni", headers=VALID_KEY)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 2. Wrong secret returns 401
# ---------------------------------------------------------------------------

def test_db_mode_wrong_secret_returns_401(db_client):
    """Prefix 'dev-secr' matches the bootstrap row; wrong suffix fails hash check."""
    client, _ = db_client
    # 'dev-secr' is the prefix (first 8 chars of 'dev-secret-key').
    # A different suffix must fail the scrypt verification.
    response = client.get("/v1/alumni", headers={"x-api-key": "dev-secr.wrongsuffix"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 3. Unknown key returns 401
# ---------------------------------------------------------------------------

def test_db_mode_unknown_key_returns_401(db_client):
    client, _ = db_client
    response = client.get("/v1/alumni", headers={"x-api-key": "xxxxxxxx.completelyunknown"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 4. Missing header returns 401
# ---------------------------------------------------------------------------

def test_db_mode_missing_header_returns_401(db_client):
    client, _ = db_client
    response = client.get("/v1/alumni")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 5. Revoked key returns 401
# ---------------------------------------------------------------------------

def test_db_mode_revoked_key_returns_401(db_client):
    """After revoking the bootstrap key, the same raw value must be rejected."""
    client, db_path = db_client
    repo = ApiKeyRepository(db_path)
    # Find the bootstrap key_id
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT key_id FROM api_keys WHERE is_active = 1"
        ).fetchone()
    finally:
        con.close()
    assert row is not None, "Expected at least one active key after bootstrap"
    repo.revoke_key(row[0])

    response = client.get("/v1/alumni", headers=VALID_KEY)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 6. Rate-limit bucket is key_id (UUID), not the raw header value
# ---------------------------------------------------------------------------

def test_db_mode_rate_limit_bucket_is_key_id(db_client, monkeypatch):
    """
    After a successful DB-mode request the rate-limit dict must contain a
    UUID bucket, not the raw 'dev-secret-key' string.
    """
    client, _ = db_client
    api_module._rate_limit_counts.clear()

    response = client.get("/v1/alumni", headers=VALID_KEY)
    assert response.status_code == 200

    buckets = list(api_module._rate_limit_counts.keys())
    # There should be at least one bucket; none of them should be the raw key
    assert "dev-secret-key" not in buckets
    # The bucket for our key should look like a UUID (36 chars with hyphens)
    uuid_buckets = [b for b in buckets if len(b) == 36 and b.count("-") == 4]
    assert len(uuid_buckets) >= 1


# ---------------------------------------------------------------------------
# 7. Env-var fallback (CSV mode) — valid key still works
# ---------------------------------------------------------------------------

def test_csv_mode_fallback_valid_key_returns_200(monkeypatch):
    """In CSV mode (no DATABASE_PATH) the original env-var comparison still works."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        response = client.get("/v1/alumni", headers=VALID_KEY)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 8. Env-var fallback (CSV mode) — wrong key returns 401
# ---------------------------------------------------------------------------

def test_csv_mode_fallback_wrong_key_returns_401(monkeypatch):
    monkeypatch.setattr(api_module, "DATABASE_PATH", None)
    with TestClient(app) as client:
        response = client.get("/v1/alumni", headers={"x-api-key": "wrong-key"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# 9. Bootstrap seeds the API_KEY env-var as a hashed row
# ---------------------------------------------------------------------------

def test_bootstrap_creates_hashed_key_row_in_db(seeded_db, monkeypatch):
    """After lifespan completes, api_keys must contain one active row."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    with TestClient(app):
        con = sqlite3.connect(seeded_db)
        try:
            count = con.execute(
                "SELECT COUNT(*) FROM api_keys WHERE is_active = 1"
            ).fetchone()[0]
            stored_hash = con.execute(
                "SELECT key_hash FROM api_keys"
            ).fetchone()[0]
        finally:
            con.close()

    assert count == 1
    # Plaintext key must not appear in stored hash
    assert "dev-secret-key" not in stored_hash
    # Hash must contain a colon separator (salt:digest format)
    assert ":" in stored_hash


# ---------------------------------------------------------------------------
# 10. Bootstrap is idempotent — two lifespan starts don't duplicate rows
# ---------------------------------------------------------------------------

def test_bootstrap_is_idempotent(seeded_db, monkeypatch):
    """Starting the application twice must not create duplicate api_keys rows."""
    monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)
    # First lifespan
    with TestClient(app):
        pass
    # Second lifespan (same DB)
    with TestClient(app):
        con = sqlite3.connect(seeded_db)
        try:
            count = con.execute("SELECT COUNT(*) FROM api_keys").fetchone()[0]
        finally:
            con.close()

    assert count == 1
