# PUT /v1/alumni/{alumni_id} — Implementation Plan
## Colaberry Nexus AI Alumni Intelligence Platform

**Status:** Planning document — no code has been changed.
**Scope:** Second write-capable API endpoint, building on the repository layer and `POST /v1/alumni`.

---

## 1. Feature Summary

Add `PUT /v1/alumni/{alumni_id}` to fully replace a mutable alumni profile in the SQLite database.

This is the smallest realistic next write feature because:
- The repository infrastructure (`_db_path`, connection-per-write pattern, in-memory cache) is already in place from `create_alumni()`
- The `AlumniAlreadyExistsError` exception already covers the email conflict case
- Only one new exception (`AlumniNotFoundError`) and one new abstract method (`update_alumni`) are required
- No new infrastructure, no new dependencies, no schema changes

**PUT semantics (full replacement):** The request body must contain all seven mutable fields. The server replaces the entire stored profile with the supplied values. Fields cannot be omitted to leave them unchanged — use PATCH for partial updates (out of scope here).

---

## 2. alumni_id Immutability

`alumni_id` is the SQLite PRIMARY KEY and cannot be changed via this endpoint.

- `alumni_id` is taken from the URL path parameter, not the request body
- The request body must **not** contain `alumni_id`; if it does, it is rejected with 422
- To change an alumni's ID, the current profile must be deleted and re-created (out of scope)

This design avoids mismatches between the path identifier and a body identifier, eliminates a class of subtle bugs, and matches standard REST PUT semantics.

---

## 3. Request Schema

### New Pydantic model: `UpdateAlumniRequest`

```python
class UpdateAlumniRequest(BaseModel):
    full_name:        str
    email:            str
    skills:           list[str] = Field(default=[], max_length=50)
    interests:        list[str] = Field(default=[], max_length=50)
    location:         str
    engagement_score: float = Field(ge=0.0, le=1.0)
    availability:     str
```

Identical to `CreateAlumniRequest` with `alumni_id` removed. The validators are the same.

### Validation rules (identical to create)

| Field | Type | Required | Constraints |
|---|---|---|---|
| `full_name` | string | Yes | Non-empty after strip |
| `email` | string | Yes | Must contain `@`; non-empty after strip |
| `skills` | list[string] | No (default `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `interests` | list[string] | No (default `[]`) | Max 50 items; each item non-empty after strip; stored lowercase |
| `location` | string | Yes | Non-empty after strip |
| `engagement_score` | float | Yes | `0.0 ≤ value ≤ 1.0` (pre-normalized; 0–100 scale not accepted) |
| `availability` | string | Yes | Non-empty after strip |

### Normalization applied at the Pydantic layer (same as create)

- `skills` and `interests`: strip each item, reject if empty, lowercase
- `full_name`, `email`, `location`, `availability`: `.strip()` applied; reject if empty after strip
- `email`: reject if `@` not present

---

## 4. Not-Found Behavior

If `alumni_id` does not exist in the database, `update_alumni()` raises `AlumniNotFoundError`.
The API layer converts this to HTTP 404 using the existing structured error envelope.

### New exception: `AlumniNotFoundError`

Defined in `src/repository.py`:

```python
class AlumniNotFoundError(Exception):
    """Raised by update_alumni() when the target alumni_id does not exist."""

    def __init__(self, alumni_id: str) -> None:
        self.alumni_id = alumni_id
        super().__init__(f"Alumni not found: {alumni_id}")
```

### Detection strategy in `SqliteAlumniRepository.update_alumni()`

A single `UPDATE ... WHERE alumni_id = ?` is executed. `cursor.rowcount` is checked before committing:

```
cursor.rowcount == 0  →  no row matched the WHERE clause  →  raise AlumniNotFoundError
cursor.rowcount == 1  →  row was updated                  →  commit and return
```

This approach uses one SQL round-trip. There is no separate `SELECT` to check existence — `rowcount` provides the same information without a second query.

**Why `rowcount` and `IntegrityError` are mutually exclusive:**
- `IntegrityError` (email conflict) only fires when a row was found and its email changed to a value already held by a different row. If the `WHERE` clause matched no rows, no constraint is evaluated.
- `rowcount == 0` only occurs when no row was found. If a row was found, either the update succeeded or `IntegrityError` fired.
- The two error conditions cannot both be true for the same call.

---

## 5. Email Duplicate-Handling Behavior

### Conflict with another profile's email → 409

If the new email is already stored on a different alumni record, SQLite raises `UNIQUE constraint failed: alumni.email`. The repository catches `sqlite3.IntegrityError` and raises `AlumniAlreadyExistsError("email", <value>)`. The API converts this to HTTP 409, consistent with `create_alumni()`.

### Updating with the same email → allowed

If the request supplies the same email already stored on the target profile (no change), SQLite's `UPDATE` simply writes the same value and does not fire the constraint. No special handling needed.

---

## 6. Repository Interface Changes

### `src/repository.py`

#### Add `AlumniNotFoundError` (new exception, defined near `AlumniAlreadyExistsError`)

```python
class AlumniNotFoundError(Exception):
    def __init__(self, alumni_id: str) -> None:
        self.alumni_id = alumni_id
        super().__init__(f"Alumni not found: {alumni_id}")
```

#### Add `update_alumni()` to `AlumniRepository` ABC

```python
@abc.abstractmethod
def update_alumni(self, alumni_id: str, profile: dict) -> dict:
    """
    Replace all mutable fields of the alumni identified by alumni_id.

    profile must contain the seven mutable fields, already normalized
    (skills and interests as list[str] lowercase, engagement_score 0.0–1.0).
    alumni_id must not be present in profile — it comes from the argument.

    Returns the updated profile dict (same shape as get_all_alumni() items,
    including alumni_id).

    Raises:
        AlumniNotFoundError      — if alumni_id does not exist.
        AlumniAlreadyExistsError — if the new email is held by a different record.
        NotImplementedError      — if the implementation does not support writes.
    """
```

#### `CsvAlumniRepository.update_alumni()`

```python
def update_alumni(self, alumni_id: str, profile: dict) -> dict:
    raise NotImplementedError(
        "CsvAlumniRepository is read-only. "
        "Set DATABASE_PATH to a seeded SQLite database to enable writes."
    )
```

#### `SqliteAlumniRepository.update_alumni()`

```python
def update_alumni(self, alumni_id: str, profile: dict) -> dict:
    import json
    import sqlite3 as _sqlite3

    row = (
        profile["full_name"],
        profile["email"],
        json.dumps(profile["skills"]),
        json.dumps(profile["interests"]),
        profile["location"],
        profile["engagement_score"],
        profile["availability"],
        alumni_id,                          # WHERE clause
    )
    con = _sqlite3.connect(self._db_path)
    try:
        cursor = con.execute(
            "UPDATE alumni SET "
            "full_name=?, email=?, skills=?, interests=?, "
            "location=?, engagement_score=?, availability=? "
            "WHERE alumni_id=?",
            row,
        )
        if cursor.rowcount == 0:
            raise AlumniNotFoundError(alumni_id)
        con.commit()
    except _sqlite3.IntegrityError as exc:
        raise AlumniAlreadyExistsError("email", profile["email"]) from exc
    finally:
        con.close()

    # Replace the matching element in the in-memory cache.
    updated = {"alumni_id": alumni_id, **profile}
    for i, p in enumerate(self._profiles):
        if p["alumni_id"] == alumni_id:
            self._profiles[i] = updated
            break
    return updated
```

**Cache update rationale:** `self._profiles` and `app.state.profiles` point to the same list object in memory (assigned once at startup via `repo.get_all_alumni()`). Replacing `self._profiles[i]` is immediately visible to `_get_profiles()` and `rank_alumni()` — no restart required. The replacement is O(n) over the profile count, which is acceptable for the current dataset size.

---

## 7. API Layer Changes

### New route

```python
@router.put(
    "/alumni/{alumni_id}",
    response_model=AlumniProfile,
    status_code=200,
    summary="Replace an alumni profile",
    description=(
        "Fully replaces the mutable fields of the alumni identified by alumni_id. "
        "alumni_id is immutable and must not be included in the request body. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 in CSV mode."
    ),
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def update_alumni_profile(alumni_id: str, body: UpdateAlumniRequest):
    repo = getattr(app.state, "repo", None)
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "CsvAlumniRepository is read-only. "
                "Set DATABASE_PATH to a seeded SQLite database to enable writes."
            ),
        )
    try:
        profile = repo.update_alumni(alumni_id, body.model_dump())
    except AlumniNotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AlumniAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: {exc.field} already exists",
        )
    return profile
```

### Route ordering note

`PUT /v1/alumni/{alumni_id}` and `GET /v1/alumni/{alumni_id}` share the same path pattern but differ by HTTP method. FastAPI handles this correctly — no ordering conflict.

### Response shape on success (HTTP 200)

Returns an `AlumniProfile` — identical shape to `GET /v1/alumni/{alumni_id}` and `POST /v1/alumni`:

```json
{
  "alumni_id": "A001",
  "full_name": "Alice Smith-Jones",
  "email": "alice.updated@example.com",
  "skills": ["python", "sql", "machine learning"],
  "interests": ["mentorship", "coaching"],
  "location": "NY",
  "engagement_score": 0.90,
  "availability": "limited"
}
```

No new response model is needed. `AlumniProfile` already matches the required shape.

---

## 8. Error Cases

| Scenario | HTTP status | `error.message` |
|---|---|---|
| Missing or wrong `x-api-key` | 401 | `"Invalid or missing API key"` |
| Required field absent or wrong type | 422 | `"Validation error"` |
| `engagement_score` outside `[0.0, 1.0]` | 422 | `"Validation error"` |
| Whitespace-only string field | 422 | `"Validation error"` |
| `email` missing `@` | 422 | `"Validation error"` |
| `alumni_id` path param not found in DB | 404 | `"Alumni not found"` |
| New email already held by a different record | 409 | `"Conflict: email already exists"` |
| Repository is CSV-backed | 503 | `"CsvAlumniRepository is read-only..."` |

All errors use the existing structured envelope:
```json
{"error": {"code": <status>, "message": "<detail>", "request_id": "<uuid>"}}
```

No new exception handler needed.

---

## 9. What Remains Unchanged

| Component | Change |
|---|---|
| `rank_alumni()` in `src/matching_engine.py` | None — updated profiles participate in match results via the shared in-memory cache |
| `GET /v1/alumni` | None |
| `GET /v1/alumni/{alumni_id}` | None |
| `POST /v1/alumni` | None |
| `POST /v1/match` | None |
| `GET /v1/health`, `/v1/version`, `/v1/metrics` | None |
| CSV fallback (`DATABASE_PATH` unset) | None — `update_alumni()` raises `NotImplementedError`, API returns 503 |
| `AlumniRepository.get_all_alumni()` | None |
| `AlumniRepository.get_alumni_by_id()` | None |
| `AlumniRepository.create_alumni()` | None |
| Auth middleware, rate limiting middleware | None |
| All existing tests | None — no existing test touches `PUT /v1/alumni/{alumni_id}` |

---

## 10. Test Plan

### 10.1 Repository tests — `tests/test_repository.py` (additions)

**`SqliteAlumniRepository.update_alumni()`:**

```
test_sqlite_repo_update_alumni_returns_updated_dict
    Call update_alumni("A001", updated_fields).
    Assert return value is dict with all eight required keys.
    Assert returned alumni_id == "A001".
    Assert returned full_name matches the new value.

test_sqlite_repo_update_alumni_persists_to_database
    Call update_alumni("A001", updated_fields).
    Open a raw sqlite3 connection to the same db_path.
    SELECT the row. Assert the stored values match the updated fields.

test_sqlite_repo_update_alumni_updates_in_memory_cache_via_get_all
    Call update_alumni("A001", updated_fields).
    Call get_all_alumni().
    Find the A001 profile in the list.
    Assert its full_name matches the updated value.

test_sqlite_repo_update_alumni_findable_with_new_values_via_get_by_id
    Call update_alumni("A001", updated_fields).
    Call get_alumni_by_id("A001").
    Assert the returned profile reflects the new values.

test_sqlite_repo_update_alumni_not_found_raises
    Call update_alumni("DOES_NOT_EXIST", any_fields).
    Assert AlumniNotFoundError is raised.
    Assert exc.alumni_id == "DOES_NOT_EXIST".

test_sqlite_repo_update_alumni_email_conflict_raises
    Call update_alumni("A001", fields with email="bob@example.com")
    (bob@example.com is A002's email).
    Assert AlumniAlreadyExistsError is raised.
    Assert exc.field == "email".

test_sqlite_repo_update_alumni_same_email_succeeds
    Call update_alumni("A001", fields where email is still "alice@example.com").
    Assert no exception is raised.
    Assert return value has alumni_id == "A001".

test_csv_repo_update_alumni_raises_not_implemented
    Instantiate CsvAlumniRepository.
    Call update_alumni("A001", any_fields).
    Assert NotImplementedError is raised.
```

### 10.2 API tests — `tests/test_api_alumni_update.py` (new file)

All DB-mode tests use `monkeypatch.setattr(api_module, "DATABASE_PATH", seeded_db)` and `TestClient(app)` as a context manager. Each test gets its own fresh seeded database from the `seeded_db` fixture.

```
test_put_alumni_returns_200_with_valid_payload
    PUT valid body to /v1/alumni/A001.
    Assert 200.

test_put_alumni_response_body_reflects_updated_values
    PUT updated full_name, email, skills.
    Assert 200. Assert response body contains the new values.
    Assert alumni_id is unchanged (still "A001").

test_put_alumni_skills_stored_lowercase
    PUT with skills=["Python", " SQL "] (mixed case).
    Assert response skills == ["python", "sql"].

test_put_alumni_not_found_returns_404
    PUT to /v1/alumni/DOES_NOT_EXIST.
    Assert 404 with structured error envelope.

test_put_alumni_email_conflict_returns_409
    PUT /v1/alumni/A001 with email="bob@example.com" (A002's email).
    Assert 409. Assert error.message contains "email".

test_put_alumni_same_email_update_succeeds
    PUT /v1/alumni/A001 with the same email alice@example.com.
    Assert 200.

test_put_alumni_requires_api_key
    PUT without x-api-key header.
    Assert 401.

test_put_alumni_wrong_api_key_returns_401
    PUT with incorrect x-api-key.
    Assert 401.

test_put_alumni_missing_required_field_returns_422
    PUT body omitting full_name.
    Assert 422 with structured error envelope.

test_put_alumni_engagement_score_out_of_range_returns_422
    PUT with engagement_score=2.0.
    Assert 422.

test_put_alumni_whitespace_only_full_name_returns_422
    PUT with full_name="   ".
    Assert 422.

test_put_alumni_invalid_email_returns_422
    PUT with email="not-an-email".
    Assert 422.

test_put_alumni_updated_profile_retrievable_by_get
    PUT with updated values.
    GET /v1/alumni/A001.
    Assert GET returns the new values, not the original ones.

test_put_alumni_updated_profile_appears_in_match_results
    Add a skill unique to A001 that was not there before (e.g., "cobol").
    PUT /v1/alumni/A001 with skills=["cobol"].
    POST /v1/match with skills=["cobol"].
    Assert A001 appears in results and has a non-zero skill_score.

test_put_alumni_returns_503_in_csv_mode
    monkeypatch DATABASE_PATH to None.
    PUT valid body.
    Assert 503. Assert "read-only" in error.message.
```

### 10.3 Unit tests — `UpdateAlumniRequest` validators

Add to `tests/test_api_alumni_update.py` or a separate `tests/test_update_alumni_request.py`:

```
test_update_request_strips_whitespace_from_full_name
test_update_request_rejects_empty_full_name
test_update_request_rejects_whitespace_only_location
test_update_request_lowercases_skills
test_update_request_strips_skills_items
test_update_request_rejects_empty_skill_item
test_update_request_rejects_engagement_score_above_one
test_update_request_rejects_engagement_score_below_zero
test_update_request_accepts_boundary_engagement_scores (0.0 and 1.0)
test_update_request_rejects_email_without_at_sign
```

---

## 11. Files Changed (implementation only — no docs)

| File | Change type | Description |
|---|---|---|
| `src/repository.py` | Modify | Add `AlumniNotFoundError`; add `update_alumni()` abstract method; implement in both concrete classes |
| `src/api.py` | Modify | Import `AlumniNotFoundError`; add `UpdateAlumniRequest` Pydantic model; add `PUT /v1/alumni/{alumni_id}` route handler |
| `tests/test_repository.py` | Modify | Add 8 repository-layer tests |
| `tests/test_api_alumni_update.py` | Create | 15 API-layer tests (including validator unit tests) |
| `directives/api_contract.md` | Modify | Add `PUT /v1/alumni/{alumni_id}` endpoint spec |
| `docs/api_examples.md` | Modify | Add Example 10: Update Alumni |
| `CHANGELOG.md` | Modify | Add entry for the new endpoint |

---

## 12. Implementation Order

Implement in this sequence to keep every intermediate step testable:

1. `src/repository.py` — Add `AlumniNotFoundError`; add `update_alumni()` abstract method; implement `CsvAlumniRepository.update_alumni()` (NotImplementedError) and `SqliteAlumniRepository.update_alumni()`
2. `tests/test_repository.py` — Add repository-layer tests; verify all pass with `python -m pytest tests/test_repository.py -v` before touching the API
3. `src/api.py` — Import `AlumniNotFoundError`; add `UpdateAlumniRequest` model; add `PUT /v1/alumni/{alumni_id}` route
4. `tests/test_api_alumni_update.py` — Add API and validator tests
5. `directives/api_contract.md`, `docs/api_examples.md`, `CHANGELOG.md` — Update docs

---

## 13. Open Questions Before Implementation

| Question | Recommendation |
|---|---|
| Should the route return 200 or 204? | 200 with the updated profile body. Returning the full profile lets callers confirm what was stored, including normalized values (lowercase skills). 204 forces a follow-up GET. |
| Should `alumni_id` in the request body be silently ignored or rejected with 422? | Rejected with 422. Silently ignoring it would hide a caller bug. If a caller sends `alumni_id` in the body, they likely misunderstood the API contract — fail loudly. This is implemented by declaring `UpdateAlumniRequest` without an `alumni_id` field; Pydantic will reject any extra fields if `model_config = ConfigDict(extra="forbid")` is set, or simply ignore them otherwise. **Recommendation: set `extra="forbid"` on `UpdateAlumniRequest` so misuse is caught at validation.** |
| Should a successful update to a seeded profile affect the golden run output? | No. `execution/run_match_local.py` loads profiles fresh from CSV each run. In-process updates do not persist across process restarts unless the DB is re-seeded. Golden run remains deterministic. |
| Should the CI add a DB-mode update validation step? | Not for Phase 1. The repository and API tests cover the behavior. A CI-level integration test that seeds, updates via HTTP, and verifies the DB can be added in Phase 2 alongside a full DB test harness. |
| What happens if `skills` and `interests` are omitted from the body (defaulting to `[]`)? | The update replaces them with empty lists. This is correct PUT semantics — the caller is responsible for sending the full desired state. Callers who want to keep existing skills must read them first with `GET /v1/alumni/{alumni_id}` and include them in the PUT body. |
