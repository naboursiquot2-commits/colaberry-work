# PROGRESS.md

Tracks implementation milestones, session activity, and verification evidence.
Format: append-only. Each entry carries a Session ID; never edit another session's entries.

---

## Baseline — Repository State Review

- [x] Repository status review and PROGRESS.md initialization
  - Date: 2026-05-29
  - Session: CC-20260529-r7m1
  - What changed: Created PROGRESS.md; no application code modified
  - Verification: user confirmed — status report reviewed and accepted
  - Notes: |
      Project is at v0.1.0 (CHANGELOG.md, src/api.py).
      Latest migration: 0004_add_api_keys_table.sql (schema version 4).
      DB-backed API key authentication Phase 1 is complete and shipped
      (src/api_key_repository.py, lifespan bootstrap shim, updated _require_api_key,
      rate-limit bucket keyed on key_id).
      240 tests collected across 14 test files; all passing.
      Next planned feature: Phase 2 key management REST endpoints
      (POST /v1/users, POST /v1/users/{user_id}/keys, DELETE /v1/keys/{key_id},
      GET /v1/keys) — repository methods already implemented in
      src/api_key_repository.py; only route handlers and tests remain.
      PROGRESS.md did not exist prior to this session.

---

## Phase 2 — Key Management REST Endpoints

- [ ] POST /v1/users — route handler and tests
  - [x] tests/test_api_key_management.py — 9 tests written (task 1 test suite)
    - Date: 2026-05-29
    - Session: CC-20260529-r7m1
    - What changed: Created tests/test_api_key_management.py with 9 tests covering
      POST /v1/users (happy path, 409 duplicate, 401 auth, 422 validation,
      503 CSV mode, idempotency, DB persistence)
    - Verification: python -m pytest tests/test_api_key_management.py -v →
      9 collected, 9 FAILED — all failures are AssertionError: 404 == <expected>,
      confirming the route is absent and the tests are structurally correct
    - Notes: No src/ changes. Tests will pass once POST /v1/users is implemented.
- [x] POST /v1/users — route handler implemented
  - Date: 2026-05-29
  - Session: CC-20260529-r7m1
  - What changed: Added CreateUserRequest and CreateUserResponse Pydantic models
    and POST /v1/users route handler to src/api.py. Route is protected by
    _require_api_key, returns 201 on success, 409 on duplicate username,
    422 on empty/whitespace-only username, 503 in CSV mode.
  - Verification: python -m pytest tests/test_api_key_management.py -v →
    9 collected, 9 passed in 1.66s
  - Notes: Only src/api.py modified. No migrations, no other src/ files touched.
- [ ] POST /v1/users/{user_id}/keys — route handler and tests
  - [x] tests/test_api_key_management.py — 10 tests written (task 2 test suite)
    - Date: 2026-05-30
    - Session: CC-20260529-r7m1
    - What changed: Appended 10 tests to tests/test_api_key_management.py and
      updated module docstring. Tests cover: 201 with key_id/key_prefix/raw_key,
      raw_key format validation, hash storage (not plaintext), 401 auth,
      404 nonexistent user_id, 503 CSV mode, description persistence,
      expires_at persistence, and end-to-end authentication with the new key.
      Also added created_user fixture that depends on the already-implemented
      POST /v1/users.
    - Verification: python -m pytest tests/test_api_key_management.py -v →
      19 collected, 10 passed, 9 FAILED — all 9 Task 1 tests pass; all 9
      new Task 2 tests fail with AssertionError: 404 == <expected> (route absent).
      Exception: test_create_key_nonexistent_user_id_returns_404 passes
      coincidentally (FastAPI 404 for unknown route matches expected 404;
      will continue to pass once endpoint is implemented for the correct reason).
    - Notes: No src/ changes. Task 2 tests will pass once
      POST /v1/users/{user_id}/keys is implemented.
- [x] POST /v1/users/{user_id}/keys — route handler implemented
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: Added CreateKeyRequest (optional description, optional expires_at),
    CreateKeyResponse (key_id, key_prefix, raw_key), and
    POST /v1/users/{user_id}/keys route handler to src/api.py. Route is
    protected by _require_api_key. Returns 503 if api_key_repo is None,
    404 if user_id is not found or inactive (explicit SQLite check — SQLite
    does not enforce FK constraints without PRAGMA foreign_keys = ON).
    Delegates to api_key_repo.create_key(); raw_key is returned once in the
    201 response and is never logged or stored in plaintext.
  - Verification: python -m pytest tests/test_api_key_management.py -v →
    19 collected, 19 passed in 3.67s.
    python -m pytest → 259 collected, 259 passed in 17.94s. No regressions.
  - Notes: Only src/api.py modified. No migrations, no repository changes.
- [ ] DELETE /v1/keys/{key_id} — route handler and tests
  - [x] tests/test_api_key_management.py — 9 tests written (task 3 test suite)
    - Date: 2026-05-30
    - Session: CC-20260529-r7m1
    - What changed: Appended 9 tests and created_key fixture to
      tests/test_api_key_management.py; updated module docstring.
      Tests cover: 204 revoke, authentication blocked after revoke, 404
      nonexistent key, 401 auth, 503 CSV mode, is_active=0 DB persistence,
      404 on second revoke, sibling key unaffected.
      created_key fixture chains created_user → POST /v1/users/{user_id}/keys
      (both endpoints already implemented).
    - Verification: python -m pytest tests/test_api_key_management.py -v →
      28 collected, 20 passed, 8 FAILED — all 19 Task 1+2 tests pass; 8 of
      9 new Task 3 tests fail with AssertionError: 404 == <expected> (route
      absent). Exception: test_revoke_key_nonexistent_key_id_returns_404
      passes coincidentally (FastAPI 404 for unknown route matches expected
      404; will continue to pass for the correct reason once endpoint exists).
    - Notes: No src/ changes. Task 3 tests will pass once
      DELETE /v1/keys/{key_id} is implemented.
- [x] DELETE /v1/keys/{key_id} — route handler implemented
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: Added DELETE /v1/keys/{key_id} route handler to src/api.py.
    Route is protected by _require_api_key. Returns 503 if api_key_repo is
    None, 404 if key is missing or already revoked, 204 on success.
    Required a pre-check via direct SQLite query (WHERE key_id = ? AND
    is_active = 1) because ApiKeyRepository.revoke_key() uses WHERE key_id = ?
    alone — its rowcount is 1 even for an already-inactive row, which would
    silently return 204 on a second revoke without the guard. No repository
    methods modified; no migrations changed.
  - Verification: python -m pytest tests/test_api_key_management.py -v →
    28 collected, 28 passed in 6.08s (required one fix: added is_active guard
    after first run showed test_revoke_key_second_revoke_returns_404 failing).
    python -m pytest → 268 collected, 268 passed in 20.00s. No regressions.
  - Notes: Only src/api.py modified.
- [ ] GET /v1/keys — route handler and tests
  - [x] tests/test_api_key_management.py — 12 tests written (task 4 test suite)
    - Date: 2026-05-30
    - Session: CC-20260529-r7m1
    - What changed: Appended 12 tests to tests/test_api_key_management.py and
      updated module docstring. Tests cover: 200 with active key list, revoked
      keys excluded, other-user keys excluded, revoked-key 401 (proxy for empty
      list — a user with zero active keys cannot authenticate to call the
      endpoint), 401 auth, 503 CSV mode, raw_key absent from response,
      key_hash absent from response, description returned, expires_at returned,
      last_used_at returned (populated by verify_key() during auth).
      No new fixtures needed; reuses created_key, created_user, db_client.
      Note on test 32: testing a literal empty-list HTTP response is impossible
      with the current design (authentication requires at least one active key),
      so the test instead asserts that a revoked key gets 401 from GET /v1/keys.
    - Verification: python -m pytest tests/test_api_key_management.py -v →
      40 collected, 28 passed, 12 FAILED — all 12 new tests fail with
      AssertionError: 404 == <expected> (route absent). No coincidental passes.
    - Notes: No src/ changes. Requires both a new list_keys() repository method
      and a GET /v1/keys route handler before these tests will pass.
- [x] GET /v1/keys — route handler implemented
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed:
      src/api_key_repository.py: added list_keys(user_id) — queries api_keys
      WHERE user_id = ? AND is_active = 1 ORDER BY created_at; returns
      list[dict] with safe fields only (key_id, key_prefix, description,
      created_at, last_used_at, expires_at); raw_key and key_hash never
      returned.
      src/api.py: added KeyEntry Pydantic model (same safe fields); added
      GET /v1/keys route handler (list_api_keys) that injects auth via
      Depends(_require_api_key) to read user_id, returns 503 if api_key_repo
      is None, delegates to api_key_repo.list_keys(auth["user_id"]).
  - Verification: python -m pytest tests/test_api_key_management.py -v →
      40 collected, 40 passed in 9.78s.
      python -m pytest → 280 collected, 280 passed in 24.14s. No regressions.
  - Notes: src/api_key_repository.py and src/api.py modified. No migrations.
