# POST /v1/alumni — Implementation Plan
## Colaberry Nexus AI Alumni Intelligence Platform

**Status:** Planning document — no code has been changed.
**Scope:** First write-capable API endpoint using the repository layer introduced in `src/repository.py`.

---

## 1. Feature Summary

Add `POST /v1/alumni` to create a new alumni profile in the SQLite database.

This is the smallest realistic first write feature because:
- It introduces no new infrastructure (SQLite already seeded and live)
- `SqliteAlumniRepository` already stores `_db_path` for exactly this purpose
- The matching engine is unaffected — new profiles immediately participate in scoring via the in-memory cache update described below
- CSV mode fails gracefully with a clear error rather than silently succeeding or corrupting state

---

## 2. Request Schema

### New Pydantic model: `CreateAlumniRequest`

```python
class CreateAlumniRequest(BaseModel):
    alumni_id:        str
    full_name:        str
    email:            str
    skills:           list[str] = Field(default=[], max_length=50)
    interests:        list[str] = Field(default=[], max_length=50)
    location:         str
    engagement_score: float = Field(ge=0.0, le=1.0)
    availability:     str
```

### Field rules

| Field | Type | Required | Constraints |
|---|---|---|---|
| `alumni_id` | `str` | Yes | Non-empty after strip; no format enforced (any string accepted) |
| `full_name` | `str` | Yes | Non-empty after strip |
| `email` | `str` | Yes | Must contain `@`; Pydantic `EmailStr` or a simple regex validator |
| `skills` | `list[str]` | No (defaults `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `interests` | `list[str]` | No (defaults `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `location` | `str` | Yes | Non-empty after strip |
| `engagement_score` | `float` | Yes | `0.0 ≤ value ≤ 1.0` (already normalized; no 0–100 scale accepted here) |
| `availability` | `str` | Yes | Non-empty after strip |

### Normalization applied at the Pydantic layer (before persistence)

- `skills` and `interests`: reuse `_strip_and_reject_empty` validator from `MatchRequest`, then lowercase each item
- `alumni_id`, `full_name`, `email`, `location`, `availability`: `.strip()` applied; reject if empty after strip

The seeded DB already stores lowercase skills/interests. Normalizing at the request boundary keeps the DB consistent regardless of what callers send.

---

## 3. Duplicate-Handling Behavior

The `alumni` table has two uniqueness constraints:
- `alumni_id TEXT PRIMARY KEY`
- `email TEXT NOT NULL UNIQUE`

Both must be checked. An `INSERT` that violates either raises `sqlite3.IntegrityError`.

### New exception: `AlumniAlreadyExistsError`

Defined in `src/repository.py`:

```python
class AlumniAlreadyExistsError(Exception):
    """Raised by create_alumni() when alumni_id or email already exists."""
    def __init__(self, field: str, value: str) -> None:
        self.field = field   # "alumni_id" or "email"
        self.value = value
        super().__init__(f"{field} already exists: {value}")
```

### Detection strategy in `SqliteAlumniRepository.create_alumni()`

`sqlite3.IntegrityError` message text is inspected to distinguish which constraint fired:

| `IntegrityError` message contains | `field` value in exception |
|---|---|
| `"alumni.alumni_id"` or `"UNIQUE constraint failed: alumni.alumni_id"` | `"alumni_id"` |
| `"alumni.email"` | `"email"` |
| Neither (unexpected) | re-raise the original `IntegrityError` |

The message format is stable across CPython's sqlite3 stdlib. It is not stable across database engines — if a PostgreSQL migration happens, the detection logic moves to the PostgreSQL driver's error codes instead.

---

## 4. Repository Interface Changes

### `src/repository.py`

Add to `AlumniRepository`:

```python
@abc.abstractmethod
def create_alumni(self, profile: dict) -> dict:
    """
    Persist a new alumni profile.

    profile dict must contain all eight required fields, already normalized
    (skills and interests as list[str], engagement_score as float 0.0–1.0).

    Returns the created profile dict (same shape as get_all_alumni() items).

    Raises:
        AlumniAlreadyExistsError — if alumni_id or email already exists.
        NotImplementedError     — if the implementation does not support writes.
    """
```

### `CsvAlumniRepository.create_alumni()`

```python
def create_alumni(self, profile: dict) -> dict:
    raise NotImplementedError(
        "CsvAlumniRepository is read-only. "
        "Set DATABASE_PATH to a seeded SQLite database to enable writes."
    )
```

### `SqliteAlumniRepository.create_alumni()`

```python
def create_alumni(self, profile: dict) -> dict:
    import json, sqlite3
    row = (
        profile["alumni_id"],
        profile["full_name"],
        profile["email"],
        json.dumps(profile["skills"]),
        json.dumps(profile["interests"]),
        profile["location"],
        profile["engagement_score"],
        profile["availability"],
    )
    try:
        con = sqlite3.connect(self._db_path)
        try:
            con.execute(
                "INSERT INTO alumni "
                "(alumni_id, full_name, email, skills, interests, "
                "location, engagement_score, availability) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            con.commit()
        finally:
            con.close()
    except sqlite3.IntegrityError as exc:
        msg = str(exc)
        if "alumni.email" in msg:
            raise AlumniAlreadyExistsError("email", profile["email"]) from exc
        raise AlumniAlreadyExistsError("alumni_id", profile["alumni_id"]) from exc

    # Update the in-memory cache so subsequent get_all_alumni() and
    # get_alumni_by_id() calls see the new profile without a restart.
    created = dict(profile)
    self._profiles.append(created)
    return created
```

**Cache update rationale:** Appending to `self._profiles` is O(1) and keeps reads consistent within the same process lifetime. It does not handle cross-process or cross-container consistency — those require a shared data store (Phase 2 / PostgreSQL). For the current single-process demo deployment this is acceptable.

---

## 5. API Layer Changes

### New route

```python
@router.post(
    "/alumni",
    response_model=AlumniProfile,
    status_code=201,
    summary="Create a new alumni profile",
    description="Persists a new alumni to the database. Requires a DB-backed deployment (DATABASE_PATH must be set).",
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def create_alumni(body: CreateAlumniRequest):
    repo = getattr(app.state, "repo", None)
    if repo is None:
        repo = _get_profiles()   # should not happen; guarded for safety
    try:
        profile = repo.create_alumni(body.model_dump())
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AlumniAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: {exc.field} already exists",
        )
    return profile
```

### Response shape on success (HTTP 201)

Returns an `AlumniProfile` — identical to the response shape of `GET /v1/alumni/{alumni_id}`:

```json
{
  "alumni_id": "A007",
  "full_name": "Jane Smith",
  "email": "jane.smith@example.com",
  "skills": ["python", "ml"],
  "interests": ["mentorship"],
  "location": "NY",
  "engagement_score": 0.8,
  "availability": "available"
}
```

No new response model is needed. `AlumniProfile` already matches the required shape.

---

## 6. Error Cases

| Scenario | HTTP status | `error.message` |
|---|---|---|
| Missing or wrong `x-api-key` | 401 | `"Invalid or missing API key"` |
| Required field absent or wrong type | 422 | `"Validation error"` |
| `skills`/`interests` item is empty or whitespace-only | 422 | `"Validation error"` |
| `engagement_score` outside `[0.0, 1.0]` | 422 | `"Validation error"` |
| `alumni_id` already exists | 409 | `"Conflict: alumni_id already exists"` |
| `email` already exists | 409 | `"Conflict: email already exists"` |
| Repository is CSV-backed (`DATABASE_PATH` not set) | 503 | `"CsvAlumniRepository is read-only..."` |

All error responses follow the existing structured envelope:
```json
{"error": {"code": <status>, "message": "<detail>", "request_id": "<uuid>"}}
```

No new exception handler needed — `HTTPException` is already handled by `_http_exception_handler` in `src/api.py`.

---

## 7. What Remains Unchanged

| Component | Change |
|---|---|
| `rank_alumni()` in `src/matching_engine.py` | None — new profiles appear in match results automatically via the cache update |
| `GET /v1/alumni` | None |
| `GET /v1/alumni/{alumni_id}` | None |
| `POST /v1/match` | None |
| `GET /v1/health` | None |
| `GET /v1/version` | None |
| `GET /v1/metrics` | None |
| CSV fallback (`DATABASE_PATH` unset) | None — `CsvAlumniRepository` raises `NotImplementedError`, API returns 503 |
| Existing `AlumniRepository.get_all_alumni()` | None |
| Existing `AlumniRepository.get_alumni_by_id()` | None |
| Auth middleware, rate limiting middleware | None |
| All existing tests | None — no existing test touches `POST /v1/alumni` |

---

## 8. Test Plan

### 8.1 Repository tests — `tests/test_repository.py` (additions)

**`SqliteAlumniRepository.create_alumni()`:**

```
test_sqlite_repo_create_alumni_returns_profile_dict
    Call create_alumni() with valid data.
    Assert return value is dict with all eight required keys.
    Assert returned alumni_id matches input.

test_sqlite_repo_create_alumni_persists_to_database
    Call create_alumni().
    Open a raw sqlite3 connection to the same db_path.
    SELECT the row. Assert it exists with correct values.

test_sqlite_repo_create_alumni_appears_in_get_all_alumni
    Call create_alumni().
    Call get_all_alumni().
    Assert the new profile is in the returned list.

test_sqlite_repo_create_alumni_findable_by_get_alumni_by_id
    Call create_alumni() with alumni_id="TEST001".
    Assert get_alumni_by_id("TEST001") returns the profile.

test_sqlite_repo_create_alumni_duplicate_id_raises_already_exists_error
    Seed the DB. Call create_alumni() with alumni_id="A001" (exists).
    Assert AlumniAlreadyExistsError is raised.
    Assert exc.field == "alumni_id".

test_sqlite_repo_create_alumni_duplicate_email_raises_already_exists_error
    Seed the DB. Call create_alumni() with a new alumni_id but an email
    that matches an existing row.
    Assert AlumniAlreadyExistsError is raised.
    Assert exc.field == "email".

test_sqlite_repo_create_alumni_skills_and_interests_stored_as_lists
    Call create_alumni() with skills=["Python", " SQL "] (mixed case).
    Assert get_alumni_by_id() returns skills=["python", "sql"]
    (normalization applied at the API/Pydantic layer before persistence).
```

**`CsvAlumniRepository.create_alumni()`:**

```
test_csv_repo_create_alumni_raises_not_implemented
    Instantiate CsvAlumniRepository.
    Call create_alumni() with any dict.
    Assert NotImplementedError is raised.
```

### 8.2 API tests — `tests/test_api_alumni_create.py` (new file)

All tests use `monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)` and `TestClient(app)` as a context manager.

```
test_post_alumni_returns_201_with_valid_payload
    POST valid body.
    Assert 201. Assert response body has all AlumniProfile fields.
    Assert returned alumni_id matches the input.

test_post_alumni_returns_location_header
    (Optional) Assert response includes Location: /v1/alumni/{alumni_id} header.
    Only add if the team wants REST-compliant 201 behavior.

test_post_alumni_requires_api_key
    POST without x-api-key header.
    Assert 401.

test_post_alumni_wrong_api_key_returns_401
    POST with incorrect x-api-key.
    Assert 401.

test_post_alumni_missing_required_field_returns_422
    POST body omitting alumni_id.
    Assert 422 with structured error envelope.

test_post_alumni_empty_string_alumni_id_returns_422
    POST with alumni_id="  " (whitespace only).
    Assert 422.

test_post_alumni_engagement_score_out_of_range_returns_422
    POST with engagement_score=1.5.
    Assert 422.

test_post_alumni_duplicate_id_returns_409
    POST the same alumni_id twice.
    Assert first returns 201, second returns 409.
    Assert error.message contains "alumni_id".

test_post_alumni_duplicate_email_returns_409
    POST two profiles with different alumni_id but same email.
    Assert first returns 201, second returns 409.
    Assert error.message contains "email".

test_post_alumni_appears_in_list_alumni
    POST a new profile.
    GET /v1/alumni. Assert the new alumni_id is in results.

test_post_alumni_retrievable_by_get_alumni_by_id
    POST a new profile with alumni_id="TEST007".
    GET /v1/alumni/TEST007. Assert 200, correct alumni_id.

test_post_alumni_new_profile_appears_in_match_results
    POST a profile with skills=["cobol"] (unique, guaranteed not in sample data).
    POST /v1/match with skills=["cobol"].
    Assert the new alumni_id appears in results.

test_post_alumni_returns_503_in_csv_mode
    monkeypatch DATABASE_PATH to None (CSV mode).
    POST valid body.
    Assert 503. Assert error detail mentions "read-only".
```

### 8.3 Unit tests — `CreateAlumniRequest` validators

Add to `tests/test_api.py` or a new `tests/test_create_alumni_request.py`:

```
test_create_alumni_request_strips_whitespace_from_string_fields
test_create_alumni_request_rejects_empty_alumni_id
test_create_alumni_request_rejects_whitespace_only_alumni_id
test_create_alumni_request_lowercases_skills
test_create_alumni_request_strips_skills_items
test_create_alumni_request_rejects_empty_skills_item
test_create_alumni_request_rejects_engagement_score_below_zero
test_create_alumni_request_rejects_engagement_score_above_one
test_create_alumni_request_accepts_zero_engagement_score
test_create_alumni_request_accepts_one_engagement_score
```

---

## 9. Files Changed (implementation only — no docs)

| File | Change type | Description |
|---|---|---|
| `src/repository.py` | Modify | Add `AlumniAlreadyExistsError` exception; add `create_alumni()` to `AlumniRepository` ABC; implement in both concrete classes |
| `src/api.py` | Modify | Add `CreateAlumniRequest` Pydantic model; add `POST /v1/alumni` route handler; import `AlumniAlreadyExistsError` |
| `tests/test_repository.py` | Modify | Add 8 new repository-layer tests |
| `tests/test_api_alumni_create.py` | Create | 13 new API-layer tests |
| `tests/test_create_alumni_request.py` | Create | 10 Pydantic validator unit tests (or append to `tests/test_api.py`) |
| `directives/api_contract.md` | Modify | Add `POST /v1/alumni` endpoint spec |
| `docs/api_examples.md` | Modify | Add Example 9: Create Alumni |
| `CHANGELOG.md` | Modify | Add entry for the new endpoint |

---

## 10. Implementation Order

Implement in this sequence to keep every intermediate step testable:

1. `src/repository.py` — Add `AlumniAlreadyExistsError` and `create_alumni()` abstract method; implement `CsvAlumniRepository.create_alumni()` (NotImplementedError) and `SqliteAlumniRepository.create_alumni()`
2. `tests/test_repository.py` — Add repository-layer tests; confirm they pass before touching the API
3. `src/api.py` — Add `CreateAlumniRequest` model and `POST /v1/alumni` route
4. `tests/test_api_alumni_create.py` — Add API-layer tests
5. `tests/test_create_alumni_request.py` — Add Pydantic validator unit tests
6. `directives/api_contract.md`, `docs/api_examples.md`, `CHANGELOG.md` — Update docs

Steps 1–2 can be verified with `python -m pytest tests/test_repository.py -v` before step 3 is started, reducing the feedback loop.

---

## 11. Open Questions Before Implementation

| Question | Recommendation |
|---|---|
| Should `alumni_id` format be enforced (e.g. must match `A\d{3}`)? | No — accept any non-empty string. Stricter format can be added later without a breaking change. |
| Should `POST /v1/alumni` return a `Location` response header? | Yes, add `response.headers["Location"] = f"/v1/alumni/{profile['alumni_id']}"` in the route handler. Low cost, correct REST behavior. |
| Should the 409 error distinguish `alumni_id` conflict from `email` conflict in the response body? | Yes — include `field` in the error detail so callers can surface the right message to users. |
| Should `engagement_score` accept the 0–100 scale (like the CSV loader) and normalize it? | No — the write API should accept only normalized values (0.0–1.0). The 0–100 normalization is a CSV-format quirk that should not leak into the write API. |
| What happens to rate limiting for write requests? | Same in-process sliding window as all other endpoints. No change needed in Phase 1. |
