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

---

## M10 — Deployment and Release Readiness

- [x] M10-T1: Deployment readiness audit
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: No files modified. Audit report produced in session.
  - Verification: user confirmed — audit findings accepted
  - Notes: Seven gaps identified; M10-T2 through M10-T7 recommended.
    Highest-priority gap: Dockerfile installs requirements.txt not lock file.

- [x] M10-T2 (part 1): Fix Dockerfile dependency installation to match CI
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: Dockerfile — changed COPY and pip install to use
    requirements-lock.txt instead of requirements.txt. Two-line change;
    ensures Docker builds install the exact same pinned transitive
    dependency tree that CI validates rather than resolving fresh.
  - Verification: Dockerfile diff reviewed — change is exactly two lines,
    no other modifications. Docker build not yet run.
  - Notes: Dockerfile only. No application code, migrations, or tests changed.

- [x] M10-T3: Update stale _BOOTSTRAP_VERSION constant in migrate_database.py
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: execution/migrate_database.py — changed _BOOTSTRAP_VERSION
    from 2 to 4. The constant stamps legacy databases (alumni table present,
    no schema_version table) at the highest migration version known to already
    be applied. Migrations 0003 (users) and 0004 (api_keys) were added in M9
    but the constant was never updated, so a legacy DB bootstrapped with the
    old value would be stamped at 2 and then attempt to re-apply 0003 and 0004
    — safe (CREATE TABLE IF NOT EXISTS) but semantically incorrect.
  - Verification: git diff — one line changed. python -m pytest
    tests/test_migrations.py -v → 23 collected, 23 passed in 0.59s.
  - Notes: execution/migrate_database.py only. No application code, tests,
    or migration SQL files changed.

- [x] M10-T4: Document RATE_LIMIT_MAX, RATE_LIMIT_WINDOW, and DB-mode capabilities in .env.example
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: .env.example — added commented-out RATE_LIMIT_MAX=60 and
    RATE_LIMIT_WINDOW=60 entries with defaults and the per-worker scaling note;
    expanded DATABASE_PATH comment to list the write-capable endpoints that
    require DB-backed mode (alumni CRUD + all four key management endpoints).
  - Verification: git diff reviewed — comments and commented-out vars only,
    no executable lines added or changed.
  - Notes: .env.example only. No application code modified.

- [x] M10-T5: Add API key management operational guidance to docs/runbook.md
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: docs/runbook.md — appended Section 6 (API Key Management)
    with six subsections: overview of DB-backed mode, initial user/key setup
    (6.1), listing active keys (6.2), key rotation with safe ordering (6.3),
    key revocation with response table (6.4), recovery when all keys are
    revoked including bootstrap-key emergency procedure (6.5), and DB-level
    key status verification (6.6).
  - Verification: git diff --stat → 173 insertions, 0 deletions. Existing
    runbook content confirmed intact (diff tail shows correct end of file).
  - Notes: docs/runbook.md only. No application code modified.

- [x] M10-T6: Update README.md to reflect current platform state
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: README.md — 104 insertions, 56 deletions across seven
    targeted sections: (1) feature list — added DB storage, key management,
    migrations, metrics/version endpoints, lock-file Docker, updated test
    count to 280; (2) Data Layer architecture — SQLite primary + CSV fallback
    + migration version; (3) API endpoints table — replaced 4-row table with
    full 13-route inventory across System/Alumni/Matching/Key Management
    groups; (4) setup — pip install now references requirements-lock.txt,
    .env.example noted, DATABASE_PATH added to example config; (5) Docker —
    added -e API_KEY to run commands, added DATABASE_PATH variant; (6) CI
    description — updated to reflect migration validation, 280 tests, golden
    run, DB-mode pass; (7) Project Structure — full current tree with
    annotations; also updated Future Improvements (removed done items),
    Notes (updated data layer reality), and removed leftover appendix section.
  - Verification: git diff --stat → 1 file, 104 insertions, 56 deletions.
  - Notes: README.md only. No application code modified.

- [x] M10-T7: Add docker-compose.yml for local deployment
  - Date: 2026-05-30
  - Session: CC-20260529-r7m1
  - What changed: Created docker-compose.yml at repo root. Builds from
    local Dockerfile; exposes 8000:8000; sets API_KEY via shell env-var
    with dev-secret-key fallback; sets DATABASE_PATH=/app/data/alumni.db;
    mounts named volume alumni_data at /app/data so the seeded SQLite DB
    persists across restarts (Docker copies image contents into a new empty
    volume on first run). Healthcheck inherited from Dockerfile instruction.
  - Verification: file content reviewed — no docker compose run yet.
  - Notes: docker-compose.yml only. No application code, Dockerfile,
    migrations, or tests modified.
