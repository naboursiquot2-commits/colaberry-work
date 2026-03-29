# Plan: Database Migration and Versioning Support

## Context

The current schema is created by `execution/seed_database.py` using a bare
`CREATE TABLE IF NOT EXISTS alumni (...)`. There is no versioning record, no
migration history, and no safe path to evolve the schema without dropping and
re-seeding the database. This plan adds the smallest migration infrastructure
that is safe, auditable, and forward-compatible with a future PostgreSQL switch.

---

## Scope of This Plan

**Changed by this plan:**
- New script: `execution/migrate_database.py`
- New directory: `execution/migrations/`
- New SQL file: `execution/migrations/0001_initial_schema.sql`
- New SQL file: `execution/migrations/0002_add_schema_version_table.sql`
- `execution/seed_database.py` — calls `migrate_database.py` before seeding
  (the public `seed()` function signature is unchanged)
- `Dockerfile` — run migrate before seed
- `.github/workflows/ci.yml` — add explicit migrate step

**Unchanged by this plan:**
- All API contracts (`GET`, `POST`, `PUT`, `DELETE` routes)
- All repository behavior (`get_all_alumni`, `create_alumni`, `update_alumni`,
  `delete_alumni`)
- CSV fallback behavior (no migration runs for CSV-mode deployments)
- `src/db.py`, `src/api.py`, `src/repository.py`, `src/matching_engine.py`
- The `alumni` table schema (no columns added or removed in Phase 1)
- All existing tests

---

## Decision: schema_version Table (Not PRAGMA user_version)

Two options for tracking the applied migration level in SQLite:

| Approach | Pros | Cons |
|---|---|---|
| `PRAGMA user_version` | Zero schema overhead; single integer; atomic | SQLite-only; no history; invisible to SQL tooling; unusable in PostgreSQL |
| `schema_version` table | Portable to PostgreSQL; stores history (which migrations ran, when); visible in any SQL client; trivially queryable | One extra table |

**Decision: `schema_version` table.**

Rationale: the architecture roadmap explicitly calls out PostgreSQL as the next
data layer. A `schema_version` table has identical DDL in both databases; the
migration runner code needs no change for Phase 2. `PRAGMA user_version` would
have to be abandoned entirely when PostgreSQL is added.

---

## Schema Version Table

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    description TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

One row is inserted per successfully applied migration. The current schema
version is `MAX(version)` across all rows. A fresh database starts with no rows
(version 0).

`applied_at` uses SQLite's `datetime('now')` default and is stored as ISO 8601
text. In PostgreSQL Phase 2 the default becomes `NOW()` — same column type,
different function name, handled by the Alembic env.

---

## Migration File Convention

Migrations live in `execution/migrations/` as numbered SQL files:

```
execution/migrations/
    0001_initial_schema.sql
    0002_add_schema_version_table.sql
    0003_<next_change>.sql
    ...
```

**Naming rules:**
- Four-digit zero-padded integer prefix
- Snake-case description
- `.sql` extension
- Prefix uniquely determines the application order
- Never renumber or reorder existing migrations

Each file contains only `ALTER TABLE`, `CREATE TABLE`, `CREATE INDEX`, or
equivalent DDL. No `INSERT`/`UPDATE`/`DELETE` — data seeding stays in
`seed_database.py`.

### Migration 0001 — initial schema

Extracts the existing `CREATE TABLE alumni` DDL from `seed_database.py` into a
tracked migration. Running this migration on a fresh database produces exactly
the same result as the current `seed_database.py`.

```sql
-- execution/migrations/0001_initial_schema.sql
CREATE TABLE IF NOT EXISTS alumni (
    alumni_id        TEXT PRIMARY KEY,
    full_name        TEXT NOT NULL,
    email            TEXT NOT NULL UNIQUE,
    skills           TEXT NOT NULL DEFAULT '[]',
    interests        TEXT NOT NULL DEFAULT '[]',
    location         TEXT NOT NULL DEFAULT '',
    engagement_score REAL NOT NULL DEFAULT 0.0,
    availability     TEXT NOT NULL DEFAULT ''
);
```

### Migration 0002 — add schema_version table

Creates the versioning table itself. Applying 0001 then 0002 produces a fully
versioned, seeded-ready database.

```sql
-- execution/migrations/0002_add_schema_version_table.sql
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    description TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

---

## Migration Runner: `execution/migrate_database.py`

### Responsibilities

1. Open the database at `db_path`
2. Bootstrap the `schema_version` table if it does not exist (covers existing
   pre-migration databases — see "Existing Database Upgrade" below)
3. Determine the current schema version: `MAX(version)` from `schema_version`
   (0 if the table is empty)
4. Discover all `.sql` files in `execution/migrations/` whose numeric prefix >
   current version, sorted ascending
5. For each pending migration:
   a. Open a transaction
   b. Execute the SQL
   c. Insert a row into `schema_version`
   d. Commit
   e. On any exception: rollback, log the failing migration name and error,
      re-raise — the database is left at the last successfully committed version
6. Return the final schema version

### Public API (importable, testable)

```python
def migrate(db_path: str, migrations_dir: str = DEFAULT_MIGRATIONS_DIR) -> int:
    """
    Apply all pending migrations to the SQLite database at db_path.

    Returns the final schema version (an integer >= 0).

    Raises:
        FileNotFoundError      if db_path does not exist and cannot be created
        sqlite3.OperationalError if a migration SQL is invalid
        MigrationError         custom exception wrapping the above, with the
                               failing migration filename in the message
    """
```

### Transaction Isolation

Each migration file runs in its own transaction. Migrations that span multiple
DDL statements are committed atomically:

```python
con = sqlite3.connect(db_path)
con.isolation_level = None          # autocommit OFF; use explicit BEGIN/COMMIT
try:
    con.execute("BEGIN")
    con.executescript(sql)          # all statements in the file
    con.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (version_number, description),
    )
    con.execute("COMMIT")
except Exception as exc:
    con.execute("ROLLBACK")
    raise MigrationError(f"Migration {filename} failed: {exc}") from exc
finally:
    con.close()
```

Note: SQLite's `executescript()` issues an implicit `COMMIT` before executing,
which can interfere with the outer transaction. The implementation must use
`execute()` for individual statements or handle this boundary carefully. The
recommended approach is to split the file on `;`, strip comments, and execute
each statement individually.

### CLI entry point

```
python execution/migrate_database.py
python execution/migrate_database.py --db data/alumni.db
python execution/migrate_database.py --db data/alumni.db --migrations execution/migrations
```

Exits 0 on success (including "already up to date"), exits 1 on any migration
failure with a human-readable error message.

---

## Existing Database Upgrade Path

Databases created before migration support was added (i.e. by the current
`seed_database.py`) have the `alumni` table but no `schema_version` table.

**Bootstrap logic:**

```
IF schema_version table does not exist:
    CREATE schema_version table
    check which migration DDL objects already exist in the DB
    IF alumni table already exists:
        record migrations 0001 and 0002 as having been applied at epoch
        (these migrations are idempotent: CREATE TABLE IF NOT EXISTS)
        set version = 2
    ELSE:
        set version = 0 and apply all migrations from 0001 upward
```

The `CREATE TABLE IF NOT EXISTS` guard in migration files makes this safe: re-
running the DDL on an existing table is a no-op. The bootstrap simply catches up
the version counter without destructive schema changes.

**In practice:** any database seeded by the current `seed_database.py` will be
detected as pre-versioned, brought to version 2 (alumni table exists, schema_version
table now created), and declared ready. The seeded data is untouched.

---

## Integration with `seed_database.py`

The `seed()` function becomes:

```python
def seed(csv_path: str = DEFAULT_CSV_PATH, db_path: str = DEFAULT_DB_PATH) -> int:
    # 1. Ensure schema is up to date
    from execution.migrate_database import migrate
    migrate(db_path)

    # 2. Upsert alumni data (unchanged)
    con = sqlite3.connect(db_path)
    ...
```

The `_CREATE_TABLE` constant and its `con.execute(_CREATE_TABLE)` call are
**removed** from `seed_database.py`. Schema creation is now exclusively owned
by the migration runner. The public `seed()` signature does not change.

`CREATE TABLE IF NOT EXISTS` remains in `0001_initial_schema.sql` as a safety
guard for idempotency — it is not removed from the migration file.

---

## Failure Handling

| Failure scenario | Behavior |
|---|---|
| Migration SQL is invalid (syntax error) | Rollback the current migration; DB stays at last committed version; `MigrationError` raised with filename |
| Partial migration (file has N statements, fails on statement K) | Rollback; none of the N statements are committed |
| `schema_version` table is missing on startup | Auto-bootstrapped before any migration logic runs |
| Migration file has wrong format (not parseable as integer prefix) | Skipped with a warning log; never applied |
| Two processes run migrate concurrently | SQLite's file-level lock serializes them; second process sees the updated version and applies nothing |
| `db_path` directory does not exist | `sqlite3.connect` raises `OperationalError` immediately; propagated as `MigrationError` |

**No automatic retry.** If a migration fails, the operator must fix the SQL,
then re-run `migrate_database.py`. The script is safe to re-run: applied
migrations are skipped.

---

## Dockerfile Changes

Current sequence:
```dockerfile
COPY execution/ ./execution/
RUN python execution/seed_database.py
```

After this plan:
```dockerfile
COPY execution/ ./execution/
RUN python execution/migrate_database.py
RUN python execution/seed_database.py
```

The migrate step is explicit and separate so a failed migration produces a
clear build error pointing at the migration runner, not the seeder. Because
`seed_database.py` now calls `migrate()` internally, running both is redundant
at build time but makes the intent auditable in the Dockerfile. Alternatively,
a single `RUN python execution/seed_database.py` continues to work since
`seed()` calls `migrate()` first — the choice is one of clarity vs brevity.

**Recommended: keep both steps** for clarity. The migrate step is a no-op when
`seed_database.py` is run immediately after, but documents the two-phase
initialization explicitly.

---

## CI Changes (`.github/workflows/ci.yml`)

Add a dedicated migration validation step before the existing seed step:

```yaml
- name: Validate migrations (fresh database)
  run: python execution/migrate_database.py --db /tmp/ci_fresh.db

- name: Validate migrations (upgrade path)
  run: |
    # Simulate a pre-migration database: seed without migrate
    python -c "
    import sqlite3, json
    con = sqlite3.connect('/tmp/ci_legacy.db')
    con.execute('''CREATE TABLE IF NOT EXISTS alumni (
        alumni_id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL,
        email     TEXT NOT NULL UNIQUE,
        skills    TEXT NOT NULL DEFAULT '[]',
        interests TEXT NOT NULL DEFAULT '[]',
        location  TEXT NOT NULL DEFAULT '',
        engagement_score REAL NOT NULL DEFAULT 0.0,
        availability TEXT NOT NULL DEFAULT ''
    )''')
    con.commit(); con.close()
    "
    python execution/migrate_database.py --db /tmp/ci_legacy.db

- name: Seed database
  run: python execution/seed_database.py
```

The existing `Seed database` and `Run DB-mode tests` steps remain unchanged.
The new steps prove that:
1. A fresh database is brought from version 0 to the latest version cleanly
2. A legacy pre-migration database (no `schema_version` table) is bootstrapped
   correctly
3. The migration runner exits 0 in both cases

---

## What Stays Unchanged

| Component | Status |
|---|---|
| `GET /v1/match`, `GET /v1/alumni`, `GET /v1/alumni/{id}`, `POST /v1/alumni`, `PUT /v1/alumni/{id}`, `DELETE /v1/alumni/{id}`, `GET /v1/health`, `GET /v1/metrics`, `GET /v1/version` | Unchanged |
| `src/api.py`, `src/db.py`, `src/repository.py`, `src/matching_engine.py` | Unchanged |
| CSV fallback behavior | Unchanged — migration runner is never called in CSV mode; the `repo` selection in `lifespan` is untouched |
| `execution/validate_sample_dataset.py`, `execution/run_match_local.py` | Unchanged |
| All existing tests (185 tests) | Must continue to pass without modification |
| `data/sample_alumni.csv` | Unchanged |
| `requirements.txt` / `requirements-lock.txt` | No new dependencies for Phase 1 (stdlib only: `sqlite3`, `pathlib`, `argparse`) |

---

## Implementation Order

1. Create `execution/migrations/0001_initial_schema.sql`
2. Create `execution/migrations/0002_add_schema_version_table.sql`
3. Write and test `execution/migrate_database.py` in isolation (no changes to
   any existing file yet)
4. Add migration tests (see test plan below); all must pass
5. Update `execution/seed_database.py`: call `migrate()` at the top of `seed()`,
   remove `_CREATE_TABLE` constant and its `con.execute` call
6. Verify existing tests still pass (no regressions)
7. Update `Dockerfile`
8. Update `.github/workflows/ci.yml`

---

## Test Plan

### New test file: `tests/test_migrations.py`

#### Section 1 — Migration runner on a fresh database

| Test | Assertion |
|---|---|
| `test_migrate_fresh_db_creates_alumni_table` | After `migrate()`, `SELECT name FROM sqlite_master WHERE type='table' AND name='alumni'` returns a row |
| `test_migrate_fresh_db_creates_schema_version_table` | After `migrate()`, `schema_version` table exists |
| `test_migrate_fresh_db_returns_correct_version` | `migrate()` returns `2` (latest migration number) |
| `test_migrate_fresh_db_schema_version_has_two_rows` | `SELECT COUNT(*) FROM schema_version` == 2 |
| `test_migrate_fresh_db_schema_version_rows_are_ordered` | Rows are version 1 and 2 |
| `test_migrate_is_idempotent_when_run_twice` | Running `migrate()` a second time returns the same version and does not change `COUNT(*)` from `schema_version` |

#### Section 2 — Migration runner on a legacy pre-migration database

| Test | Assertion |
|---|---|
| `test_migrate_legacy_db_bootstraps_schema_version` | Given a DB with `alumni` table but no `schema_version`, `migrate()` creates `schema_version` |
| `test_migrate_legacy_db_records_prior_migrations` | After bootstrap, `MAX(version)` == 2 |
| `test_migrate_legacy_db_alumni_data_survives` | Rows present before `migrate()` are still present after |
| `test_migrate_legacy_db_is_idempotent` | Re-running `migrate()` on a bootstrapped legacy DB changes nothing |

#### Section 3 — Incremental apply

| Test | Assertion |
|---|---|
| `test_migrate_applies_only_pending_migrations` | Given a DB at version 1 (only `0001` applied), running `migrate()` applies only `0002`; `COUNT(*)` from `schema_version` == 2 |
| `test_migrate_skips_applied_migrations` | Given a DB already at version 2, `migrate()` returns 2 with no new rows inserted |

#### Section 4 — Failure handling

| Test | Assertion |
|---|---|
| `test_migrate_bad_sql_raises_migration_error` | Given a migration file containing invalid SQL, `migrate()` raises `MigrationError` with the filename in the message |
| `test_migrate_bad_sql_leaves_db_at_prior_version` | After the `MigrationError`, `MAX(version)` in `schema_version` is the version before the failing migration |
| `test_migrate_bad_sql_does_not_partially_apply` | Tables added by prior statements in the failing migration do not exist (rollback was complete) |

#### Section 5 — Integration with `seed_database.py`

| Test | Assertion |
|---|---|
| `test_seed_migrates_before_inserting_data` | After `seed()`, `schema_version` table exists |
| `test_seed_with_no_existing_db_produces_versioned_db` | Fresh path: `seed()` creates DB, alumni table, schema_version table, and inserts data |
| `test_seed_with_legacy_db_upgrades_and_preserves_data` | Pre-existing un-versioned DB: `seed()` upgrades schema then upserts; row count and values unchanged |
| `test_seed_with_already_versioned_db_is_idempotent` | Already-migrated DB: calling `seed()` a second time produces the same final state |

#### Section 6 — CLI

| Test | Assertion |
|---|---|
| `test_migrate_cli_exits_0_on_success` | `subprocess.run(["python", "execution/migrate_database.py", "--db", tmp_db])` returns returncode 0 |
| `test_migrate_cli_exits_1_on_missing_migrations_dir` | Passing `--migrations /nonexistent` returns returncode 1 with an error message on stderr |

---

## Phase 2 — PostgreSQL + Alembic

When PostgreSQL is added, the custom migration runner is replaced by Alembic.
No application-layer changes are required.

### Migration path from Phase 1 to Phase 2

1. Add `alembic` and `psycopg2-binary` to `requirements.txt`
2. `alembic init alembic` in the repo root
3. Configure `alembic/env.py` to read `DATABASE_URL` env var; detect SQLite vs
   PostgreSQL from the URL scheme
4. Translate `execution/migrations/0001_*.sql` and `0002_*.sql` into Alembic
   revision files with `upgrade()` / `downgrade()` functions
5. For existing SQLite databases: run a one-time script to stamp the Alembic
   `alembic_version` table at the equivalent head revision
6. Retire `execution/migrate_database.py` — replaced by `alembic upgrade head`

### Why this plan preserves Phase 2 compatibility

- The `schema_version` table is not Alembic's `alembic_version` table, but the
  migration DDL files (`0001_*.sql`) are plain SQL that translates directly into
  Alembic `op.execute()` calls
- The `alumni` table schema is identical in SQLite and PostgreSQL for all
  Phase 1 column types (`TEXT`, `REAL`, `INTEGER`); no type casting is needed
- The `migrate_database.py` runner uses only stdlib (`sqlite3`, `pathlib`,
  `argparse`) — zero dependencies to remove when switching to Alembic
- The `schema_version` bootstrap logic (detecting legacy databases) remains
  useful in Alembic form as a `stamp` command

### Alembic entry points (Phase 2)

```bash
# Apply all pending migrations
alembic upgrade head

# Check current version
alembic current

# Roll back one migration
alembic downgrade -1

# Generate a new migration from model diff
alembic revision --autogenerate -m "add_bio_column"
```

The `Dockerfile` and CI steps replace `python execution/migrate_database.py`
with `alembic upgrade head`. The `seed_database.py` call to `migrate()` is
replaced with a pre-check: `alembic current` must equal `head` before seeding,
or seeding calls `alembic upgrade head` directly.

---

## Open Questions

1. **`executescript()` vs individual execute() calls**: SQLite's `executescript()`
   issues an implicit COMMIT, breaking explicit transaction management. The runner
   must split migration files on `;` and execute statements individually, or accept
   the implicit commit behavior and remove the wrapping `BEGIN`. Decision should be
   explicit in the implementation directive.

2. **Downgrade support**: This plan does not include `downgrade()` migrations.
   If a migration is applied and a deployment is rolled back, the old code must
   run against the new schema. For additive-only migrations (new nullable columns,
   new indexes) this is safe. If a migration removes a column, a downgrade script
   is required. This constraint should be documented as a migration authoring rule
   ("all Phase 1 migrations must be additive and non-breaking").

3. **Multi-worker safety**: SQLite's file lock serializes concurrent writes but
   in a multi-container deployment (e.g. `--workers 4`), each worker process
   calls `migrate()` at startup via `seed_database.py`. The first worker acquires
   the lock and applies migrations; subsequent workers see the updated
   `schema_version` and skip. This is safe but adds startup latency. The
   recommended mitigation: run `migrate_database.py` as a separate init step in
   the container entrypoint before uvicorn starts (already addressed in the
   Dockerfile section above).

4. **Test isolation**: `tests/test_seed_database.py` uses `tmp_path` and imports
   the `seed()` function directly. After `seed()` is changed to call `migrate()`,
   those tests will implicitly exercise the migration path. This is desirable but
   should be verified — no existing test should break because the migration runner
   is now in the call path.
