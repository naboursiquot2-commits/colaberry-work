# Plan: DELETE /v1/alumni/{alumni_id}

## Overview

Adds a hard-delete endpoint that removes an alumni profile permanently from the SQLite
database and the in-memory cache. The CSV repository remains read-only and returns 503.

---

## Hard Delete vs Soft Delete

**Decision: hard delete.**

Rationale:
- The dataset is a demo/dev fixture; there is no audit, compliance, or referential-integrity
  requirement that would require a `deleted_at` tombstone.
- Soft delete would require adding a nullable column to the schema, changing every
  `SELECT` query to add `WHERE deleted_at IS NULL`, and updating the seeder — significant
  surface area for a feature with no stated retention requirement.
- Hard delete is the minimal correct implementation. A soft-delete variant can be added
  later if a directive explicitly requires it.

---

## HTTP Contract

| Item | Value |
|------|-------|
| Method | `DELETE` |
| Path | `/v1/alumni/{alumni_id}` |
| Auth | `x-api-key` header required |
| Success status | **204 No Content** |
| Success body | none |
| Not found | **404** — alumni_id does not exist |
| CSV mode | **503** — read-only repository |
| Missing auth | **401** |

**Why 204 and not 200?** RFC 9110 §9.3.5: a DELETE that succeeds with no entity to
return should use 204. The resource no longer exists, so there is nothing meaningful
to include in the response body.

---

## Error Reuse

`AlumniNotFoundError` already exists in `src/repository.py` and carries `.alumni_id`.
No new exception class is needed.

---

## Repository Interface Changes

### Abstract method (AlumniRepository)

```python
@abc.abstractmethod
def delete_alumni(self, alumni_id: str) -> None:
    """
    Permanently removes the alumni identified by alumni_id.

    Raises:
        AlumniNotFoundError: if no row with alumni_id exists.
    """
```

### CsvAlumniRepository

```python
def delete_alumni(self, alumni_id: str) -> None:
    raise NotImplementedError(
        "CsvAlumniRepository is read-only. "
        "Set DATABASE_PATH to a seeded SQLite database to enable writes."
    )
```

### SqliteAlumniRepository

Implementation outline:

```python
def delete_alumni(self, alumni_id: str) -> None:
    con = sqlite3.connect(self._db_path)
    try:
        cur = con.execute(
            "DELETE FROM alumni WHERE alumni_id = ?", (alumni_id,)
        )
        con.commit()
    finally:
        con.close()

    if cur.rowcount == 0:
        raise AlumniNotFoundError(alumni_id)

    # Remove from in-memory cache
    self._profiles = [p for p in self._profiles if p["alumni_id"] != alumni_id]
```

Key design points:

- **Single round-trip**: one `DELETE WHERE alumni_id = ?` — no prior `SELECT`.
- **`rowcount == 0` → not found**: SQLite sets `rowcount` to 0 if the `WHERE` clause
  matched no rows. This is checked *after* `con.close()` because the cursor object
  remains valid after the connection closes.
- **No `IntegrityError` possible**: a `DELETE` cannot violate a uniqueness constraint;
  only foreign-key constraints could fire, and there are no foreign keys in this schema.
- **Cache update is a new list**: unlike create (append) and update (index replacement),
  delete uses a list comprehension to rebuild `self._profiles` without the deleted
  entry. This avoids mutating the list while iterating and keeps the reference clean.
- **`app.state.profiles` consistency**: `app.state.profiles` is assigned `repo.get_all_alumni()`
  at startup, which returns `self._profiles` directly. After delete rebuilds `self._profiles`
  with a new list object, `app.state.profiles` still points to the old list. To keep
  both in sync the API route must either (a) re-fetch from the repo after every delete,
  or (b) clear `app.state.profiles` so `_get_profiles()` refetches.

  **Chosen approach (b)**: the route handler sets `app.state.profiles = repo.get_all_alumni()`
  after a successful delete. This is the same pattern used implicitly by create/update
  via in-place mutation; delete uses an explicit reassignment since list comprehension
  creates a new object.

  Alternative (a) — just call `_get_profiles()` which reads `app.state.profiles` — would
  not work because `app.state.profiles` still holds the old reference. Re-assigning
  `app.state.profiles = repo.get_all_alumni()` in the route handler is explicit and safe.

---

## API Route

```python
@router.delete(
    "/alumni/{alumni_id}",
    status_code=204,
    summary="Delete an alumni profile",
    description=(
        "Permanently removes the alumni identified by alumni_id. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 in CSV mode."
    ),
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def delete_alumni_profile(alumni_id: str):
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
        repo.delete_alumni(alumni_id)
    except AlumniNotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # Sync app.state.profiles with the updated repository cache
    app.state.profiles = repo.get_all_alumni()
    # Return None → FastAPI emits 204 No Content with no body
```

---

## Files to Change

| File | Change |
|------|--------|
| `src/repository.py` | Add `delete_alumni()` abstract method; implement in `CsvAlumniRepository` (raises `NotImplementedError`) and `SqliteAlumniRepository` (single DELETE + rowcount check + cache rebuild) |
| `src/api.py` | Add `DELETE /v1/alumni/{alumni_id}` route; sync `app.state.profiles` after success |
| `tests/test_repository.py` | Add Section 9 (delete_alumni — SqliteAlumniRepository) and Section 10 (delete_alumni — CsvAlumniRepository read-only guard) |
| `tests/test_api_alumni_delete.py` | New file — full API-layer test suite (see test plan below) |
| `directives/api_contract.md` | Add `DELETE /v1/alumni/{alumni_id}` spec |
| `docs/api_examples.md` | Add Example 11: Delete Alumni |

No changes to `execution/`, `data/`, `Dockerfile`, or other directives.

---

## Implementation Order

1. `src/repository.py` — add abstract method and both implementations
2. `tests/test_repository.py` — add delete sections; run; must pass
3. `src/api.py` — add route
4. `tests/test_api_alumni_delete.py` — create; run; must pass
5. `directives/api_contract.md` — add DELETE spec
6. `docs/api_examples.md` — add Example 11

---

## Test Plan

### Repository tests (`tests/test_repository.py` — Section 9)

| Test | Assertion |
|------|-----------|
| `test_sqlite_repo_delete_alumni_removes_from_database` | After `delete_alumni("A001")`, direct `sqlite3` query returns no row |
| `test_sqlite_repo_delete_alumni_removed_from_get_all` | After delete, `get_all_alumni()` does not contain `"A001"` |
| `test_sqlite_repo_delete_alumni_not_findable_by_get_by_id` | After delete, `get_alumni_by_id("A001")` returns `None` |
| `test_sqlite_repo_delete_alumni_count_decreases` | `len(get_all_alumni())` is 5 after deleting one of the 6 seeded rows |
| `test_sqlite_repo_delete_alumni_not_found_raises` | `delete_alumni("DOES_NOT_EXIST")` raises `AlumniNotFoundError`; `.alumni_id == "DOES_NOT_EXIST"` |

### Repository tests (Section 10 — CsvAlumniRepository read-only guard)

| Test | Assertion |
|------|-----------|
| `test_csv_repo_delete_alumni_raises_not_implemented` | `csv_repo.delete_alumni("A001")` raises `NotImplementedError` |

### API tests (`tests/test_api_alumni_delete.py`)

**1. Happy path**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_returns_204` | `DELETE /v1/alumni/A001` → 204 |
| `test_delete_alumni_response_has_no_body` | Response body is empty (`response.text == ""`) |

**2. Authentication**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_requires_api_key` | No header → 401 |
| `test_delete_alumni_wrong_api_key_returns_401` | Wrong key → 401 |

**3. Not found (404)**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_not_found_returns_404` | `DELETE /v1/alumni/DOES_NOT_EXIST` → 404; `error.code == 404` |

**4. Visibility after delete**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_removed_from_get_by_id` | After DELETE, `GET /v1/alumni/A001` → 404 |
| `test_delete_alumni_removed_from_list` | After DELETE, `GET /v1/alumni` results do not contain `A001` |
| `test_delete_alumni_removed_from_match_results` | After deleting the only alumnus with `"python"` skill (requires a targeted fixture), `POST /v1/match` with `skills=["python"]` returns no results for that ID |

**5. Double delete**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_twice_returns_404_on_second` | First DELETE → 204; second DELETE same ID → 404 |

**6. CSV mode (503)**

| Test | Assertion |
|------|-----------|
| `test_delete_alumni_returns_503_in_csv_mode` | `monkeypatch(DATABASE_PATH=None)` → 503; `"read-only"` in error message |

---

## Error Response Shapes

**404 Not Found**
```json
{"error": {"code": 404, "message": "Alumni not found", "request_id": "..."}}
```

**503 Service Unavailable**
```json
{"error": {"code": 503, "message": "CsvAlumniRepository is read-only. Set DATABASE_PATH to a seeded SQLite database to enable writes.", "request_id": "..."}}
```

**204 No Content** — no body.

---

## Open Questions

1. **Cascade to match results**: after delete the profile is gone from `self._profiles`
   and `app.state.profiles`, so subsequent `POST /v1/match` calls will not see it.
   No extra logic needed.

2. **Idempotency**: `DELETE` is conventionally idempotent (repeated calls are safe), but
   returning 204 on the first call and 404 on subsequent calls is also widely accepted
   (RFC 9110 does not mandate 204 for repeated deletes). The current plan returns 404
   on repeat — this is the simpler implementation and consistent with `update_alumni`'s
   not-found behavior. If strict idempotency (always 204) is required, the directive
   must say so explicitly.

3. **Bulk delete**: not in scope. If needed, a separate endpoint (e.g., `DELETE /v1/alumni`
   with a filter body) should be planned independently.

4. **Re-creation after delete**: because this is a hard delete, a deleted `alumni_id`
   can be reused by a subsequent `POST /v1/alumni`. No special handling needed.
