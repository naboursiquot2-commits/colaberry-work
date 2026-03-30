"""
src/api_key_repository.py

Database-backed API key management for the alumni platform.

Keys are never stored in plaintext.  The raw key is returned exactly once
(on creation) and immediately discarded — only the scrypt hash is persisted.

Key format
----------
    {8-char hex prefix}.{56-char hex secret}       (65 chars total)

The prefix is stored in plaintext in api_keys.key_prefix to enable O(1)
prefix lookup before running the (expensive) hash verification step.

Hash format stored in api_keys.key_hash
----------------------------------------
    {32-char hex salt}:{64-char hex scrypt digest}

Parameters: n=2**14, r=8, p=1, dklen=32.  All standard-library — no
third-party packages.

Env-var bootstrap key format
-----------------------------
The API_KEY environment variable may be an arbitrary string (e.g.
"dev-secret-key").  It has no "." separator, so the prefix is derived as
the first 8 characters of the raw value.  This is handled transparently by
_key_prefix() and create_key(raw_key=...).

Dependencies
------------
    hashlib, hmac, os, secrets, sqlite3, uuid — all stdlib.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import uuid


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _key_prefix(raw_key: str) -> str:
    """
    Extract the lookup prefix from a raw key string.

    For keys in canonical format ("{prefix}.{secret}") the prefix is the
    segment before the first ".".  For arbitrary strings (e.g. env-var
    bootstrap values) the first 8 characters are used.
    """
    if "." in raw_key:
        return raw_key.split(".", 1)[0]
    return raw_key[:8]


def _generate_key() -> tuple[str, str]:
    """
    Generate a new random API key.

    Returns:
        (raw_key, key_prefix) where
            key_prefix = secrets.token_hex(4)          # 8 hex chars
            raw_key    = f"{key_prefix}.{secret}"      # 65 chars total
    """
    prefix = secrets.token_hex(4)   # 8 hex chars
    secret = secrets.token_hex(28)  # 56 hex chars
    return f"{prefix}.{secret}", prefix


def _hash_key(raw_key: str) -> str:
    """
    Hash a raw API key with scrypt.

    Returns a string in the form "{hex_salt}:{hex_digest}" suitable for
    storage in api_keys.key_hash.
    """
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        raw_key.encode(),
        salt=salt,
        n=2 ** 14,
        r=8,
        p=1,
        dklen=32,
    )
    return f"{salt.hex()}:{digest.hex()}"


def _verify_hash(raw_key: str, stored_hash: str) -> bool:
    """
    Verify a raw key against a stored "{hex_salt}:{hex_digest}" string.

    Uses hmac.compare_digest for constant-time comparison.
    Returns False (never raises) on any format or computation error.
    """
    try:
        salt_hex, digest_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.scrypt(
        raw_key.encode(),
        salt=salt,
        n=2 ** 14,
        r=8,
        p=1,
        dklen=32,
    )
    return hmac.compare_digest(actual, expected)


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class ApiKeyRepository:
    """
    SQLite-backed storage for users and API keys.

    The users and api_keys tables must already exist before this class is
    instantiated.  Run execute/migrate_database.py (migrations 0003 and
    0004) first.

    All public methods open a fresh connection, perform their work, and
    close immediately — safe for multi-worker deployments where each uvicorn
    worker maintains its own process state.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # -----------------------------------------------------------------------
    # Users
    # -----------------------------------------------------------------------

    def create_user(self, username: str) -> dict:
        """
        Insert a new user row.

        Returns {"user_id": ..., "username": ...}.
        Raises ValueError if username already exists.
        """
        user_id = str(uuid.uuid4())
        con = sqlite3.connect(self._db_path)
        try:
            try:
                con.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    (user_id, username),
                )
                con.commit()
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"Username already exists: {username!r}") from exc
        finally:
            con.close()
        return {"user_id": user_id, "username": username}

    # -----------------------------------------------------------------------
    # Keys
    # -----------------------------------------------------------------------

    def create_key(
        self,
        user_id: str,
        description: str = "",
        expires_at: str | None = None,
        *,
        raw_key: str | None = None,
    ) -> dict:
        """
        Issue a new API key for user_id.

        If raw_key is provided the caller's value is used directly instead
        of generating a random one.  This parameter is reserved for the
        env-var bootstrap shim in the API lifespan; application code should
        always omit it so a cryptographically random key is generated.

        The returned raw_key is the only opportunity to capture the
        plaintext value — it is never stored or logged.

        Returns {"raw_key": ..., "key_id": ..., "key_prefix": ...}.
        """
        if raw_key is None:
            raw_key, prefix = _generate_key()
        else:
            prefix = _key_prefix(raw_key)

        key_id = str(uuid.uuid4())
        key_hash = _hash_key(raw_key)

        con = sqlite3.connect(self._db_path)
        try:
            con.execute(
                """
                INSERT INTO api_keys
                    (key_id, user_id, key_prefix, key_hash, description, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (key_id, user_id, prefix, key_hash, description, expires_at),
            )
            con.commit()
        finally:
            con.close()

        return {"raw_key": raw_key, "key_id": key_id, "key_prefix": prefix}

    def revoke_key(self, key_id: str) -> bool:
        """
        Set is_active = 0 for the given key.

        Returns True if the row existed, False if not found.
        """
        con = sqlite3.connect(self._db_path)
        try:
            cursor = con.execute(
                "UPDATE api_keys SET is_active = 0 WHERE key_id = ?",
                (key_id,),
            )
            con.commit()
        finally:
            con.close()
        return cursor.rowcount > 0

    def get_key_id_by_prefix(self, prefix: str) -> str | None:
        """
        Return the key_id for an active key with the given prefix.

        Used by the rate-limit middleware for lightweight O(1) bucket
        assignment without the cost of a full scrypt verification.
        Returns None if no active key matches.
        """
        con = sqlite3.connect(self._db_path)
        try:
            row = con.execute(
                "SELECT key_id FROM api_keys WHERE key_prefix = ? AND is_active = 1",
                (prefix,),
            ).fetchone()
        finally:
            con.close()
        return row[0] if row else None

    def verify_key(self, raw_key: str) -> dict | None:
        """
        Authenticate a raw API key.

        Steps:
            1. Extract the prefix and look up the row by prefix.
            2. Check is_active on both the key and its owner user.
            3. Check expires_at (None = never expires).
            4. Verify the scrypt hash (constant-time comparison).
            5. On success: update last_used_at and return caller info.

        Returns {"key_id": ..., "user_id": ..., "username": ...} on success.
        Returns None on any failure — invalid key, revoked, expired, or
        unknown prefix.  Never raises.
        """
        try:
            prefix = _key_prefix(raw_key)
            con = sqlite3.connect(self._db_path)
            try:
                row = con.execute(
                    """
                    SELECT ak.key_id,
                           ak.user_id,
                           ak.key_hash,
                           ak.is_active,
                           ak.expires_at,
                           u.username,
                           u.is_active AS user_active
                    FROM   api_keys ak
                    JOIN   users    u  ON u.user_id = ak.user_id
                    WHERE  ak.key_prefix = ?
                    """,
                    (prefix,),
                ).fetchone()

                if row is None:
                    return None

                key_id, user_id, key_hash, is_active, expires_at, username, user_active = row

                if not is_active or not user_active:
                    return None

                if expires_at is not None:
                    from datetime import datetime, timezone
                    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    if now_str > expires_at:
                        return None

                if not _verify_hash(raw_key, key_hash):
                    return None

                con.execute(
                    "UPDATE api_keys SET last_used_at = datetime('now') WHERE key_id = ?",
                    (key_id,),
                )
                con.commit()

            finally:
                con.close()

            return {"key_id": key_id, "user_id": user_id, "username": username}

        except Exception:
            return None
