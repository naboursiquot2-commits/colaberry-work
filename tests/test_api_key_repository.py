"""
tests/test_api_key_repository.py

Unit tests for src/api_key_repository.py.

Covers:
    1. create_user — persistence, return shape, duplicate rejection
    2. create_key  — return shape, prefix derivation, plaintext not stored,
                     default is_active
    3. verify_key  — happy path, wrong secret, unknown prefix, last_used_at
                     update, revoked key, inactive user, expired key
    4. revoke_key  — sets is_active=0, returns True/False correctly
    5. Hash helpers — roundtrip, distinct keys don't match, hash not plaintext

All tests use tmp_path so the real data/alumni.db is never touched.
Each test gets its own fresh migrated database.
"""

import sqlite3
from pathlib import Path

import pytest

from execution.migrate_database import migrate
from src.api_key_repository import (
    ApiKeyRepository,
    _hash_key,
    _key_prefix,
    _verify_hash,
)


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def repo(tmp_path) -> ApiKeyRepository:
    """Return an ApiKeyRepository backed by a freshly migrated temp DB."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    return ApiKeyRepository(db_path)


@pytest.fixture()
def user_and_key(repo):
    """Create one user and one key; return (user_info, key_info, repo)."""
    user = repo.create_user("testuser")
    key = repo.create_key(user["user_id"], description="test key")
    return user, key, repo


# ---------------------------------------------------------------------------
# 1. create_user
# ---------------------------------------------------------------------------

def test_create_user_returns_user_id_and_username(repo):
    """create_user() must return a dict with user_id and username."""
    result = repo.create_user("alice")
    assert "user_id" in result
    assert result["username"] == "alice"
    assert result["user_id"]  # non-empty


def test_create_user_persists_to_database(repo):
    """create_user() must write a row readable from the database."""
    result = repo.create_user("alice")
    con = sqlite3.connect(repo._db_path)
    try:
        row = con.execute(
            "SELECT user_id, username, is_active FROM users WHERE user_id = ?",
            (result["user_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row is not None
    assert row[1] == "alice"
    assert row[2] == 1  # is_active default


def test_create_user_duplicate_username_raises_value_error(repo):
    """create_user() with a duplicate username must raise ValueError."""
    repo.create_user("alice")
    with pytest.raises(ValueError, match="already exists"):
        repo.create_user("alice")


# ---------------------------------------------------------------------------
# 2. create_key
# ---------------------------------------------------------------------------

def test_create_key_returns_raw_key_key_id_prefix(repo):
    """create_key() must return raw_key, key_id, and key_prefix."""
    user = repo.create_user("alice")
    result = repo.create_key(user["user_id"])
    assert "raw_key" in result
    assert "key_id" in result
    assert "key_prefix" in result
    assert result["raw_key"]
    assert result["key_id"]


def test_create_key_raw_key_not_stored_in_database(repo):
    """The plaintext raw_key must not appear anywhere in the api_keys row."""
    user = repo.create_user("alice")
    result = repo.create_key(user["user_id"])
    raw_key = result["raw_key"]
    con = sqlite3.connect(repo._db_path)
    try:
        row = con.execute(
            "SELECT key_hash FROM api_keys WHERE key_id = ?",
            (result["key_id"],),
        ).fetchone()
    finally:
        con.close()
    assert raw_key not in row[0]


def test_create_key_prefix_matches_raw_key_start(repo):
    """key_prefix must be the segment before the first '.' in raw_key."""
    user = repo.create_user("alice")
    result = repo.create_key(user["user_id"])
    assert result["raw_key"].startswith(result["key_prefix"] + ".")


def test_create_key_default_is_active(repo):
    """A freshly created key must have is_active = 1."""
    user = repo.create_user("alice")
    result = repo.create_key(user["user_id"])
    con = sqlite3.connect(repo._db_path)
    try:
        row = con.execute(
            "SELECT is_active FROM api_keys WHERE key_id = ?",
            (result["key_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# 3. verify_key
# ---------------------------------------------------------------------------

def test_verify_key_valid_key_returns_dict(user_and_key):
    """verify_key() with a valid key must return key_id, user_id, username."""
    user, key, repo = user_and_key
    result = repo.verify_key(key["raw_key"])
    assert result is not None
    assert result["key_id"] == key["key_id"]
    assert result["user_id"] == user["user_id"]
    assert result["username"] == user["username"]


def test_verify_key_wrong_secret_returns_none(user_and_key):
    """verify_key() with the correct prefix but wrong secret must return None."""
    user, key, repo = user_and_key
    prefix = key["key_prefix"]
    tampered = f"{prefix}.{'0' * 56}"
    assert repo.verify_key(tampered) is None


def test_verify_key_unknown_prefix_returns_none(repo):
    """verify_key() with an unrecognised prefix must return None."""
    assert repo.verify_key("unknown1.abc") is None


def test_verify_key_updates_last_used_at(user_and_key):
    """A successful verify_key() must set last_used_at to a non-null value."""
    user, key, repo = user_and_key
    # Before first use last_used_at is NULL
    con = sqlite3.connect(repo._db_path)
    try:
        before = con.execute(
            "SELECT last_used_at FROM api_keys WHERE key_id = ?",
            (key["key_id"],),
        ).fetchone()[0]
    finally:
        con.close()
    assert before is None

    repo.verify_key(key["raw_key"])

    con = sqlite3.connect(repo._db_path)
    try:
        after = con.execute(
            "SELECT last_used_at FROM api_keys WHERE key_id = ?",
            (key["key_id"],),
        ).fetchone()[0]
    finally:
        con.close()
    assert after is not None


def test_verify_key_revoked_key_returns_none(user_and_key):
    """verify_key() must return None after the key has been revoked."""
    user, key, repo = user_and_key
    repo.revoke_key(key["key_id"])
    assert repo.verify_key(key["raw_key"]) is None


def test_verify_key_inactive_user_returns_none(user_and_key):
    """verify_key() must return None when the owning user is disabled."""
    user, key, repo = user_and_key
    con = sqlite3.connect(repo._db_path)
    try:
        con.execute(
            "UPDATE users SET is_active = 0 WHERE user_id = ?",
            (user["user_id"],),
        )
        con.commit()
    finally:
        con.close()
    assert repo.verify_key(key["raw_key"]) is None


def test_verify_key_expired_key_returns_none(repo):
    """verify_key() must return None for a key with expires_at in the past."""
    user = repo.create_user("alice")
    key = repo.create_key(
        user["user_id"],
        expires_at="2000-01-01 00:00:00",  # definitely in the past
    )
    assert repo.verify_key(key["raw_key"]) is None


# ---------------------------------------------------------------------------
# 4. revoke_key
# ---------------------------------------------------------------------------

def test_revoke_key_returns_true_for_existing_key(user_and_key):
    """revoke_key() must return True when the key row exists."""
    user, key, repo = user_and_key
    assert repo.revoke_key(key["key_id"]) is True


def test_revoke_key_sets_is_active_to_0(user_and_key):
    """After revoke_key(), the api_keys row must have is_active = 0."""
    user, key, repo = user_and_key
    repo.revoke_key(key["key_id"])
    con = sqlite3.connect(repo._db_path)
    try:
        row = con.execute(
            "SELECT is_active FROM api_keys WHERE key_id = ?",
            (key["key_id"],),
        ).fetchone()
    finally:
        con.close()
    assert row[0] == 0


def test_revoke_key_returns_false_for_missing_key(repo):
    """revoke_key() must return False for an unknown key_id."""
    assert repo.revoke_key("nonexistent-key-id") is False


# ---------------------------------------------------------------------------
# 5. Hash helpers
# ---------------------------------------------------------------------------

def test_hash_and_verify_roundtrip():
    """_verify_hash(_hash_key(k), k) must return True for the same key."""
    raw = "test.rawkey12345"
    stored = _hash_key(raw)
    assert _verify_hash(raw, stored) is True


def test_different_keys_do_not_verify_against_same_hash():
    """_verify_hash must return False for a different key against the same hash."""
    raw = "test.rawkey12345"
    other = "test.differentkey"
    stored = _hash_key(raw)
    assert _verify_hash(other, stored) is False


def test_hash_does_not_contain_plaintext():
    """The stored hash must not contain the plaintext key as a substring."""
    raw = "test.rawkey12345"
    stored = _hash_key(raw)
    assert raw not in stored


def test_key_prefix_canonical_format():
    """_key_prefix extracts the segment before the first '.'."""
    assert _key_prefix("abcd1234.secret") == "abcd1234"


def test_key_prefix_no_dot_uses_first_eight_chars():
    """_key_prefix falls back to the first 8 chars for keys without '.'."""
    assert _key_prefix("dev-secret-key") == "dev-secr"
