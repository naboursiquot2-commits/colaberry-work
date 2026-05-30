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
