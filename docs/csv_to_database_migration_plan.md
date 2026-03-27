# CSV to Database Migration Plan
## Colaberry Nexus AI Alumni Intelligence Platform

**Status:** Planning document — no code has been changed.
**Scope:** Replace CSV-backed alumni data loading with a database-backed data layer.

---

## 1. Database Choice: SQLite → PostgreSQL

### Phase 1: SQLite

**Recommended for the first version.**

| Criterion | SQLite |
|---|---|
| New dependencies | None — `sqlite3` is Python stdlib |
| Infrastructure | Zero — single file on disk |
| CI compatibility | Runs without any service setup |
| Read-only workload | Ideal — SQLite handles concurrent reads well |
| Migration path | Standard SQL; connection string swap upgrades to PostgreSQL |

SQLite is the correct Phase 1 choice because it adds no infrastructure dependency, requires no new packages, and the existing workload is entirely read-heavy. The matching engine receives a `list[dict]` — the source of that list (CSV or DB) is irrelevant to it.

**Phase 2 (future):** PostgreSQL when a write API is added or multi-instance deployments require a shared data source. The schema designed below is compatible with PostgreSQL without changes.

---

## 2. Target Schema

### Design Decision: JSON Columns for Skills and Interests

The current CSV stores skills and interests as comma-separated strings (e.g. `"Python, SQL, Data Analysis"`). The matching engine expects `list[str]`.

Three modelling options:

| Option | Pros | Cons |
|---|---|---|
| JSON array column (`TEXT`) | Minimal query complexity; direct `list[str]` deserialization | Not indexable; no relational querying |
| Normalized junction tables | Fully relational; filterable at the DB layer | Requires joins; query complexity increases |
| PostgreSQL `ARRAY` type | Native array operations | PostgreSQL-only; breaks SQLite compatibility |

**Phase 1 recommendation:** JSON array columns. The matching engine performs all filtering and scoring in Python. The DB layer's only job is to hydrate `list[dict]` at startup. Normalization can be deferred to Phase 2 when query-time filtering by skill is a requirement.

### Table: `alumni`

```sql
CREATE TABLE alumni (
    alumni_id        TEXT PRIMARY KEY,
    full_name        TEXT NOT NULL,
    email            TEXT NOT NULL UNIQUE,
    skills           TEXT NOT NULL DEFAULT '[]',   -- JSON array: '["python","sql"]'
    interests        TEXT NOT NULL DEFAULT '[]',   -- JSON array: '["mentorship"]'
    location         TEXT NOT NULL DEFAULT '',
    engagement_score REAL NOT NULL DEFAULT 0.0,    -- stored normalized (0.0–1.0)
    availability     TEXT NOT NULL DEFAULT ''
);
```

**Constraints:**
- `alumni_id` is the natural key (matches existing CSV values: A001–A006)
- `email` is unique
- `engagement_score` is stored pre-normalized (0.0–1.0), eliminating the 0–100 ambiguity present in the CSV
- `skills` and `interests` are stored as JSON arrays of lowercase stripped strings, matching the normalization already applied by `load_alumni_profiles_csv()`

### No additional tables in Phase 1

Junction tables (`alumni_skills`, `alumni_interests`) are deferred to Phase 2. They are the correct long-term model but add join complexity without benefit until DB-layer filtering is required.

---

## 3. CSV Field Mapping

| CSV column | DB column | Type | Transformation |
|---|---|---|---|
| `alumni_id` | `alumni_id` | `TEXT PRIMARY KEY` | Strip whitespace |
| `full_name` | `full_name` | `TEXT NOT NULL` | Strip whitespace |
| `email` | `email` | `TEXT NOT NULL UNIQUE` | Strip whitespace |
| `skills` | `skills` | `TEXT` (JSON array) | Split on comma → lowercase + strip → `json.dumps(list)` |
| `interests` | `interests` | `TEXT` (JSON array) | Split on comma → lowercase + strip → `json.dumps(list)` |
| `location` | `location` | `TEXT NOT NULL` | Strip whitespace |
| `engagement_score` | `engagement_score` | `REAL NOT NULL` | Parse float; normalize `> 1.0` by `/100`; `"N/A"` → `0.0` |
| `availability` | `availability` | `TEXT NOT NULL` | Strip whitespace |

The normalization logic for `skills`, `interests`, and `engagement_score` currently lives in `load_alumni_profiles_csv()` in `src/matching_engine.py`. It must be applied identically during the seed step so the DB contains clean data, not raw CSV values.

---

## 4. Repository / Data-Access Layer Changes

### New: `src/db.py`

A new module responsible for all database I/O. Keeps `src/api.py` and `src/matching_engine.py` unchanged.

```python
# src/db.py  (outline — not implemented yet)

import json
import sqlite3


def get_connection(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with row_factory set to sqlite3.Row."""
    ...


def load_alumni_profiles_db(db_path: str) -> list[dict]:
    """
    Load all alumni from the database and return list[dict] matching
    the schema expected by rank_alumni().

    Deserializes skills and interests from JSON arrays.
    Returns the same structure as load_alumni_profiles_csv().
    """
    ...
```

The return type of `load_alumni_profiles_db()` is identical to `load_alumni_profiles_csv()`. The matching engine and all API endpoints receive the same `list[dict]` regardless of source.

### Changes to `src/api.py`

One change only: the lifespan function switches loader based on a new env var.

```python
# Current (CSV):
app.state.profiles = load_alumni_profiles_csv(DATA_PATH)

# After migration:
if DATABASE_PATH:
    app.state.profiles = load_alumni_profiles_db(DATABASE_PATH)
else:
    app.state.profiles = load_alumni_profiles_csv(DATA_PATH)
```

`DATABASE_PATH` defaults to `None`, preserving CSV behaviour until the DB is explicitly configured. This allows a parallel-run period where both paths are tested.

### New: `execution/seed_database.py`

One-time (and repeatable) script that:
1. Reads `data/sample_alumni.csv`
2. Applies the same normalization as `load_alumni_profiles_csv()`
3. Creates the `alumni` table if it does not exist
4. Upserts all rows (INSERT OR REPLACE) so it is safe to rerun

### Changes to `src/matching_engine.py`

**None.** `rank_alumni()` is not touched. `load_alumni_profiles_csv()` remains for backward compatibility and local development without a DB.

### No changes to existing API endpoints

All route handlers, request/response models, pagination, auth, and middleware are unchanged. The data layer is an implementation detail of the lifespan startup, invisible to API consumers.

---

## 5. Environment Configuration Changes

### New env vars

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `None` | Path to SQLite file. If set, DB loader is used instead of CSV. |

### `.env.example` additions

```
# Path to SQLite database file (optional; if unset, CSV loader is used)
# DATABASE_PATH=data/alumni.db
```

### Transition strategy

Both loaders coexist during the migration period:
- `DATABASE_PATH` unset → CSV (current behaviour, unchanged)
- `DATABASE_PATH` set → DB loader

This allows CI to validate the DB path independently before CSV is removed.

---

## 6. Migration Risks

### Data fidelity during seeding
**Risk:** The seed script must apply identical normalization to what `load_alumni_profiles_csv()` applies today. Any divergence (e.g. different whitespace handling, case differences) will produce different match scores and break the golden run.
**Mitigation:** After seeding, run `execution/run_match_local.py` against the DB-loaded profiles and compare output to the CSV-loaded golden output. Add an explicit assertion that both loaders return byte-identical profiles for the 6 sample records.

### Engagement score double-normalization
**Risk:** If the seed script stores the raw CSV value (e.g. `75`) in the DB, and the DB loader applies the `> 1.0` normalization again, the score becomes `0.0075` instead of `0.75`.
**Mitigation:** Store engagement scores pre-normalized in the DB. The `> 1.0` check belongs in the seed script only. The DB loader reads the float directly.

### Golden run still loads from CSV
**Risk:** `execution/run_match_local.py` calls `load_alumni_profiles_csv()` directly. After migration, this will continue to pass — but it tests the CSV path, not the DB path.
**Mitigation:** Add a parallel golden run that uses `load_alumni_profiles_db()`. Both should be gated in CI.

### SQLite file location in Docker
**Risk:** If `DATABASE_PATH` points to a file inside the container image, data updates require a rebuild. If it points to a volume mount, the volume must be seeded before the container starts.
**Mitigation:** For Phase 1 (read-only, static data), baking the seeded DB into the image is acceptable. The seed script runs at image build time as a `RUN` step in the Dockerfile. For Phase 2 (write API), a persistent volume or external database is required.

### SQLite concurrent write limitations
**Risk:** SQLite allows only one writer at a time. With `--workers 4`, concurrent write requests would serialize or fail.
**Mitigation:** Phase 1 is read-only. No writes occur through the API. This risk surfaces only when a write API is added — at that point, move to PostgreSQL.

---

## 7. Test Impact

### New tests required

| Test | Location | Purpose |
|---|---|---|
| `test_load_alumni_profiles_db_returns_correct_schema` | `tests/test_matching_engine.py` | DB loader returns list of dicts with correct keys and types |
| `test_load_alumni_profiles_db_matches_csv_output` | `tests/test_matching_engine.py` | DB and CSV loaders return identical profiles for seeded data |
| `test_seed_database_is_idempotent` | `tests/test_matching_engine.py` or new `tests/test_db.py` | Running seed twice produces the same result (INSERT OR REPLACE) |

### Existing tests: no changes

All 43 existing tests exercise the API surface and matching logic. They are decoupled from the data loader by `app.state.profiles`. They continue to pass unchanged.

### Test fixtures

Tests for `load_alumni_profiles_db()` should use a temporary SQLite file (via `tmp_path` pytest fixture) seeded with the 6 sample records, not the production DB file.

---

## 8. CI Updates

### Additional steps in `.github/workflows/ci.yml`

```yaml
- name: Seed test database
  run: python execution/seed_database.py

- name: Run deterministic golden run (DB path)
  run: DATABASE_PATH=data/alumni.db python execution/run_match_local.py
```

The existing CSV-based validation and golden run steps remain. Both paths are validated in CI during the transition period. Once CSV is deprecated, the CSV steps are removed.

---

## 9. Documentation Updates

| Document | Update needed |
|---|---|
| `docs/runbook.md` | Add triage scenario: DB file missing or unreadable |
| `.env.example` | Add `DATABASE_PATH` (commented out) |
| `directives/matching_sop.md` | Update data loading section to describe DB loader |
| `docs/architecture_and_roadmap.md` | Update Data Layer section from CSV to SQLite |
| `CHANGELOG.md` | Add entry when DB migration is shipped |

---

## 10. First Implementation Phase

Scoped to introduce the DB loader without removing the CSV path.

**Step 1 — Schema and seed script**
- Create `execution/seed_database.py`
- Create `data/alumni.db` by running the seed against the sample CSV
- Add `data/alumni.db` to `.gitignore` (generated artifact, not committed)

**Step 2 — DB loader**
- Create `src/db.py` with `load_alumni_profiles_db(db_path: str) -> list[dict]`
- Write unit tests comparing DB and CSV loader output on the 6 sample records

**Step 3 — API integration**
- Add `DATABASE_PATH` env var to `src/api.py`
- Update lifespan to use DB loader when `DATABASE_PATH` is set
- No API behavior changes; no API tests change

**Step 4 — CI gate**
- Add seed step and DB-path golden run to `ci.yml`
- Both CSV and DB paths validated in CI

**Step 5 — Dockerfile update**
- Add `RUN python execution/seed_database.py` to the image build
- Set `DATABASE_PATH=data/alumni.db` as the default runtime env var in the Dockerfile

**Step 6 — CSV deprecation (follow-on PR)**
- Remove CSV-based startup path from `src/api.py`
- Remove `DATA_PATH` env var
- Remove CSV validation step from CI
- Archive `load_alumni_profiles_csv()` (or retain in `matching_engine.py` as a utility for scripts)

Steps 1–5 can ship as a single PR with no API behavior change and all existing tests green.
Step 6 ships as a follow-on once the DB path has been validated in a deployed environment.
