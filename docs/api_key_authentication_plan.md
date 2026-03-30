# Plan: Database-Backed API Key Authentication

## Status: Planning — no application code has been changed

---

## Goal

Replace the single `API_KEY` environment variable with a database-backed API key
system where keys are hashed at rest, can be revoked per-key, and are linked to
named user accounts.
The `x-api-key` request header remains the only authentication surface — no
endpoint signatures change.

---

## What Does Not Change

- All existing endpoints (`/v1/alumni`, `/v1/match`, `/v1/health`, `/v1/metrics`)
- The `x-api-key` request header field name
- 401 response shape for invalid/missing keys
- The matching engine and CSV fallback path
- Rate-limit enforcement mechanism (only the bucket key changes)
- Test fixtures and `API_KEY=dev-secret-key` for the test suite

---

## Database Schema

### Table: `users`

Represents an account that owns one or more API keys.

```sql
CREATE TABLE IF NOT EXISTS users (
    user_id    TEXT PRIMARY KEY,           -- UUID
    username   TEXT NOT NULL UNIQUE,
    is_active  INTEGER NOT NULL DEFAULT 1, -- 1 = active, 0 = disabled
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Table: `api_keys`

One row per issued key.  Keys are never stored in plaintext.

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    key_id       TEXT PRIMARY KEY,              -- UUID
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    key_prefix   TEXT NOT NULL UNIQUE,          -- first 8 chars of raw key; used for O(1) lookup
    key_hash     TEXT NOT NULL,                 -- scrypt(raw_key, salt) hex digest + salt, colon-separated
    description  TEXT NOT NULL DEFAULT '',
    is_active    INTEGER NOT NULL DEFAULT 1,    -- 0 = revoked
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,                          -- updated on every successful auth
    expires_at   TEXT                           -- NULL = never expires
);
```

**Key format:** `{8-char prefix}.{56-char secret}` (64 chars total, URL-safe).
The prefix indexes into `api_keys.key_prefix`; the full raw key is verified
against `key_hash`.

**Hash format stored in `key_hash`:** `{hex_salt}:{hex_digest}` where the salt is
16 random bytes and the digest is `hashlib.scrypt(raw_key, salt, n=2**14, r=8,
p=1)`.  All values are in Python's standard library — no third-party packages
required.

---

## Migration Files

Two new files added to `execution/migrations/`:

| File | Description |
|---|---|
| `0003_add_users_table.sql` | Creates the `users` table |
| `0004_add_api_keys_table.sql` | Creates the `api_keys` table |

Both use `CREATE TABLE IF NOT EXISTS` so they are safe to re-run.

`_BOOTSTRAP_VERSION` in `execute/migrate_database.py` must be updated from `2`
to `4` when these migrations are added (so legacy-database bootstrap stamps all
four versions).

---

## New Module: `src/api_key_repository.py`

Single-responsibility module: all DB operations for API key authentication.

### Public interface

```python
class ApiKeyRepository:
    def __init__(self, db_path: str) -> None: ...

    def verify_key(self, raw_key: str) -> dict | None:
        """
        Look up the key by its prefix, verify the hash, check is_active on
        both the key and its owner user, and check expires_at.

        Returns a dict with {"key_id": ..., "user_id": ..., "username": ...}
        on success; None on any failure (wrong key, revoked, expired, unknown
        prefix).  Updates last_used_at on success.

        Never raises — callers treat None as 401.
        """

    def revoke_key(self, key_id: str) -> bool:
        """Set is_active=0 for the key. Returns True if the row existed."""

    def create_user(self, username: str) -> dict:
        """
        Insert a new user row; returns {"user_id": ..., "username": ...}.
        Raises ValueError if username already exists.
        """

    def create_key(
        self,
        user_id: str,
        description: str = "",
        expires_at: str | None = None,
    ) -> dict:
        """
        Generate a new raw key, hash it, insert the row.
        Returns {"raw_key": ..., "key_id": ..., "key_prefix": ...}.
        The raw_key is returned exactly once and never stored.
        """
```

### Key generation helper (module-private)

```python
def _generate_key() -> tuple[str, str]:
    """
    Returns (raw_key, key_prefix).
    raw_key  = f"{prefix}.{secrets.token_hex(28)}"   # 8 + 1 + 56 = 65 chars
    prefix   = secrets.token_hex(4)                  # 8 hex chars
    """

def _hash_key(raw_key: str) -> str:
    """
    Returns "{hex_salt}:{hex_digest}" using hashlib.scrypt.
    Parameters: n=2**14, r=8, p=1, dklen=32.
    """

def _verify_hash(raw_key: str, stored_hash: str) -> bool:
    """Constant-time comparison via hmac.compare_digest."""
```

---

## Changes to `src/api.py`

### 1. Startup: environment-variable bootstrap shim

On startup, if `DATABASE_PATH` points to an existing file, attempt to load an
`ApiKeyRepository`.  If `API_KEY` is set and no active key with that value
exists in the database yet, create a system user `"_env_bootstrap"` and insert
a pre-hashed key so the existing env-var workflow continues to work without
any operator action.

```
Startup order:
  1. migrate_database (already happens in Docker build, not at startup)
  2. Load SqliteAlumniRepository OR CsvAlumniRepository  (unchanged)
  3. IF DATABASE_PATH is a file:
       a. Instantiate ApiKeyRepository(DATABASE_PATH)
       b. Store as app.state.api_key_repo
       c. Run bootstrap shim: if API_KEY env var is set and no active key
          matches, call api_key_repo.create_user("_env_bootstrap") then
          api_key_repo.create_key(user_id, description="bootstrapped from API_KEY env var")
          — but store the RAW KEY derived from the env-var value, not a random one.
          To achieve this: accept an optional `raw_key` parameter in create_key()
          that overrides random generation (used only during bootstrap).
     ELSE:
       app.state.api_key_repo = None
```

When `app.state.api_key_repo` is `None`, the system falls back to the current
single-key string comparison (`x_api_key == _API_KEY`).  This means CSV-mode
deployments without a DATABASE_PATH are unaffected.

### 2. `_require_api_key` dependency

```python
def _require_api_key(
    x_api_key: str | None = Header(default=None),
    request: Request = None,
) -> dict | None:
    repo: ApiKeyRepository | None = getattr(app.state, "api_key_repo", None)

    if repo is not None:
        # DB-backed path
        if x_api_key is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        result = repo.verify_key(x_api_key)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return result  # {"key_id": ..., "user_id": ..., "username": ...}
    else:
        # Env-var fallback (unchanged behaviour)
        if x_api_key != _API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return None
```

The return value is not used by any existing endpoint — adding it is backward
compatible.  Future management endpoints can use it to identify the caller.

### 3. Rate limiting key

Change the rate-limit bucket key from `x_api_key or "anonymous"` to
`key_info["key_id"] if key_info else (x_api_key or "anonymous")`.

This means:
- In DB mode: rate-limit is per database key ID (stable across key rotation if
  the same `key_id` is reused, isolated per key otherwise)
- In env-var fallback mode: behaviour is identical to today

---

## Phases

### Phase 1 (this plan) — DB auth with env-var shim

**Scope:** Infrastructure only — no new HTTP endpoints.

Deliverables:
1. `execution/migrations/0003_add_users_table.sql`
2. `execution/migrations/0004_add_api_keys_table.sql`
3. `src/api_key_repository.py` with `ApiKeyRepository`
4. Updated `src/api.py`: lifespan bootstrap shim, updated `_require_api_key`, updated rate-limit key
5. Updated `_BOOTSTRAP_VERSION = 4` in `execution/migrate_database.py`
6. Tests (see below)
7. Updated directives and runbook

### Phase 2 (future) — Key management endpoints

**Scope:** REST endpoints for key lifecycle.  Not in this plan.

Planned endpoints (for future planning document):
- `POST /v1/users` — create a user
- `POST /v1/users/{user_id}/keys` — issue a key; returns raw key once
- `DELETE /v1/keys/{key_id}` — revoke a key
- `GET /v1/keys` — list keys for the authenticated user (no raw key returned)

These endpoints will be protected by the same `_require_api_key` dependency.

---

## Unchanged Components

| Component | Why unchanged |
|---|---|
| All existing endpoint handlers | Auth is a dependency, not inline logic |
| `MatchRequest` validation | Unrelated |
| `AlumniRepository` / `SqliteAlumniRepository` | Separate concern |
| `matching_engine.py` | Unrelated |
| CSV fallback path | Falls back to env-var auth automatically |
| `x-api-key` header field name | Compatibility requirement |
| 401 response body `{"detail": "Invalid or missing API key"}` | Compatibility requirement |
| `API_KEY` env-var requirement at startup | Still required; bootstrap shim reads it |

---

## Test Plan

### `tests/test_api_key_repository.py`

**`ApiKeyRepository.create_user`**
1. `test_create_user_returns_user_id_and_username` — returned dict has both keys
2. `test_create_user_persists_to_database` — row present after call
3. `test_create_user_duplicate_username_raises_value_error`

**`ApiKeyRepository.create_key`**
4. `test_create_key_returns_raw_key_key_id_prefix` — all three fields present
5. `test_create_key_raw_key_not_stored_in_db` — `key_hash` column does not contain raw key
6. `test_create_key_prefix_matches_raw_key_start` — `raw_key[:8] == key_prefix`
7. `test_create_key_default_is_active` — `is_active=1` in DB

**`ApiKeyRepository.verify_key`**
8. `test_verify_key_valid_key_returns_dict` — `{"key_id": ..., "user_id": ..., "username": ...}`
9. `test_verify_key_wrong_secret_returns_none`
10. `test_verify_key_unknown_prefix_returns_none`
11. `test_verify_key_updates_last_used_at`
12. `test_verify_key_revoked_key_returns_none`
13. `test_verify_key_inactive_user_returns_none`
14. `test_verify_key_expired_key_returns_none` — `expires_at` in the past

**`ApiKeyRepository.revoke_key`**
15. `test_revoke_key_returns_true_for_existing_key`
16. `test_revoke_key_sets_is_active_to_0`
17. `test_revoke_key_returns_false_for_missing_key`

**Hash helpers**
18. `test_hash_and_verify_roundtrip` — `_verify_hash(raw, _hash_key(raw))` is True
19. `test_different_keys_do_not_match` — `_verify_hash(other, _hash_key(raw))` is False
20. `test_hash_is_not_plaintext` — raw key does not appear as substring of stored hash

### `tests/test_api_db_auth.py`

**DB-mode authentication (uses SqliteAlumniRepository + ApiKeyRepository)**
21. `test_valid_db_key_returns_200` — authenticated request succeeds
22. `test_invalid_secret_returns_401` — same prefix, wrong secret
23. `test_unknown_key_returns_401` — completely unknown value
24. `test_missing_header_returns_401`
25. `test_revoked_key_returns_401` — revoke then request
26. `test_rate_limit_keyed_by_key_id` — same key_id accumulates counts (not by raw value)

**Env-var fallback path (no DATABASE_PATH set / no api_key_repo)**
27. `test_fallback_valid_env_key_returns_200`
28. `test_fallback_invalid_key_returns_401`

**Bootstrap shim**
29. `test_bootstrap_creates_env_key_row_in_db` — after lifespan with `API_KEY` set, a row
    exists in `api_keys` with `is_active=1`
30. `test_bootstrap_is_idempotent` — running lifespan twice does not create duplicate rows

---

## Security Notes

1. **scrypt parameters** (`n=2**14, r=8, p=1`) are deliberately conservative for a demo
   deployment.  Production use should increase `n` to at least `2**16`.
2. **Timing safety**: `verify_key` uses `hmac.compare_digest` for hash comparison to
   prevent timing attacks.
3. **Prefix exposure**: The 8-char prefix is stored in plaintext and appears in the raw
   key.  This is intentional (enables O(1) DB lookup) and not a security risk —
   the prefix alone cannot authenticate.
4. **Raw key returned once**: `create_key` returns the plaintext key exactly once.
   It is never logged, stored, or returned again.  Operators must copy it at
   issuance time.
5. **`API_KEY` bootstrap**: The env-var value is hashed before storage.  The plaintext
   env-var value is still required at startup to verify it matches the bootstrap row on
   subsequent restarts.  This is a backward-compat shim, not a long-term pattern.
