"""
tests/test_migrations.py

Tests for execution/migrate_database.py — the SQLite migration runner.

Covers:
    1. Fresh database: migrations applied from version 0 to latest
    2. Legacy database: alumni table exists, no schema_version → bootstrap
    3. Incremental apply: only pending migrations are applied
    4. Failure/rollback: bad SQL rolls back and leaves DB at prior version
    5. Seed integration: seed() creates schema_version and handles legacy DBs
    6. CLI: exit codes for success and missing migrations directory

All tests use tmp_path so the real data/alumni.db is never touched.
"""

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from execution.migrate_database import (
    DEFAULT_MIGRATIONS_DIR,
    MigrationError,
    migrate,
)
from execution.seed_database import DEFAULT_CSV_PATH, seed


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _get_tables(db_path: str) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        con.close()


def _get_version_rows(db_path: str) -> list[dict]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT version, description FROM schema_version ORDER BY version"
        ).fetchall()
        return [{"version": r[0], "description": r[1]} for r in rows]
    finally:
        con.close()


def _get_max_version(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        row = con.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()
        return row[0]
    finally:
        con.close()


def _alumni_count(db_path: str) -> int:
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM alumni").fetchone()[0]
    finally:
        con.close()


# ---------------------------------------------------------------------------
# 1. Fresh database
# ---------------------------------------------------------------------------

def test_migrate_fresh_db_creates_alumni_table(tmp_path):
    """migrate() on an empty path must create the alumni table."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    assert "alumni" in _get_tables(db_path)


def test_migrate_fresh_db_creates_schema_version_table(tmp_path):
    """migrate() on an empty path must create the schema_version table."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    assert "schema_version" in _get_tables(db_path)


def test_migrate_fresh_db_returns_correct_version(tmp_path):
    """migrate() must return the highest migration number (4 after Phase 1 auth migrations)."""
    db_path = str(tmp_path / "test.db")
    result = migrate(db_path)
    assert result == 4


def test_migrate_fresh_db_has_four_version_rows(tmp_path):
    """After a fresh migration, schema_version must have exactly 4 rows."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    rows = _get_version_rows(db_path)
    assert len(rows) == 4


def test_migrate_fresh_db_version_rows_are_ordered(tmp_path):
    """The four version rows must be for versions 1, 2, 3, and 4 in order."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    rows = _get_version_rows(db_path)
    assert rows[0]["version"] == 1
    assert rows[1]["version"] == 2
    assert rows[2]["version"] == 3
    assert rows[3]["version"] == 4


def test_migrate_is_idempotent(tmp_path):
    """Running migrate() twice must produce the same version and row count."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    migrate(db_path)
    assert _get_max_version(db_path) == 4
    assert len(_get_version_rows(db_path)) == 4


# ---------------------------------------------------------------------------
# 2. Legacy database bootstrap
# ---------------------------------------------------------------------------

def _make_legacy_db(db_path: str, insert_row: bool = False) -> None:
    """Create a database that looks like it was seeded before migration support:
    alumni table exists, no schema_version table."""
    con = sqlite3.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE alumni (
                alumni_id        TEXT PRIMARY KEY,
                full_name        TEXT NOT NULL,
                email            TEXT NOT NULL UNIQUE,
                skills           TEXT NOT NULL DEFAULT '[]',
                interests        TEXT NOT NULL DEFAULT '[]',
                location         TEXT NOT NULL DEFAULT '',
                engagement_score REAL NOT NULL DEFAULT 0.0,
                availability     TEXT NOT NULL DEFAULT ''
            )
        """)
        if insert_row:
            con.execute(
                "INSERT INTO alumni (alumni_id, full_name, email, location, availability) "
                "VALUES (?, ?, ?, ?, ?)",
                ("A001", "Alice Smith", "alice@example.com", "NY", "mentor"),
            )
        con.commit()
    finally:
        con.close()


def test_migrate_legacy_db_bootstraps_schema_version(tmp_path):
    """migrate() on a legacy DB must create the schema_version table."""
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path)
    migrate(db_path)
    assert "schema_version" in _get_tables(db_path)


def test_migrate_legacy_db_records_prior_migrations(tmp_path):
    """After bootstrap + pending migrations, schema_version must be at version 4.

    Bootstrap stamps versions 1 and 2 (the migrations that were already applied
    by the old seed_database.py).  The runner then applies the pending migrations
    0003 and 0004, bringing the total to version 4.
    """
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path)
    migrate(db_path)
    assert _get_max_version(db_path) == 4
    rows = _get_version_rows(db_path)
    assert len(rows) == 4
    assert rows[0]["version"] == 1
    assert rows[1]["version"] == 2
    assert rows[2]["version"] == 3
    assert rows[3]["version"] == 4


def test_migrate_legacy_db_alumni_data_survives(tmp_path):
    """Any rows already in the alumni table must survive the bootstrap."""
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path, insert_row=True)
    migrate(db_path)
    assert _alumni_count(db_path) == 1


def test_migrate_legacy_db_is_idempotent(tmp_path):
    """Running migrate() twice on a bootstrapped legacy DB changes nothing."""
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path, insert_row=True)
    migrate(db_path)
    migrate(db_path)
    assert _get_max_version(db_path) == 4
    assert len(_get_version_rows(db_path)) == 4
    assert _alumni_count(db_path) == 1


# ---------------------------------------------------------------------------
# 3. Incremental apply
# ---------------------------------------------------------------------------

def _make_db_at_version_1(db_path: str) -> None:
    """Set up a database that has migration 0001 applied but not 0002.
    This simulates a DB where schema_version already exists (at version 1)
    but the add_schema_version migration (0002) has not run yet."""
    con = sqlite3.connect(db_path)
    try:
        con.execute("""
            CREATE TABLE alumni (
                alumni_id        TEXT PRIMARY KEY,
                full_name        TEXT NOT NULL,
                email            TEXT NOT NULL UNIQUE,
                skills           TEXT NOT NULL DEFAULT '[]',
                interests        TEXT NOT NULL DEFAULT '[]',
                location         TEXT NOT NULL DEFAULT '',
                engagement_score REAL NOT NULL DEFAULT 0.0,
                availability     TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE schema_version (
                version     INTEGER NOT NULL,
                description TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        con.execute(
            "INSERT INTO schema_version (version, description) VALUES (?, ?)",
            (1, "initial_schema"),
        )
        con.commit()
    finally:
        con.close()


def test_migrate_applies_only_pending_migrations(tmp_path):
    """Given a DB at version 1, migrate() must apply only migrations 0002, 0003, 0004."""
    db_path = str(tmp_path / "partial.db")
    _make_db_at_version_1(db_path)
    result = migrate(db_path)
    assert result == 4
    rows = _get_version_rows(db_path)
    # The manually inserted version-1 row plus the three newly applied rows
    assert len(rows) == 4
    assert rows[1]["version"] == 2
    assert "schema_version" in rows[1]["description"]


def test_migrate_skips_applied_migrations(tmp_path):
    """A fully migrated DB (version 4) must produce no new rows on re-run."""
    db_path = str(tmp_path / "test.db")
    migrate(db_path)
    before = len(_get_version_rows(db_path))
    migrate(db_path)
    after = len(_get_version_rows(db_path))
    assert before == after == 4


# ---------------------------------------------------------------------------
# 4. Failure and rollback
# ---------------------------------------------------------------------------

def _write_migration(directory: Path, filename: str, sql: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(sql, encoding="utf-8")


def test_migrate_bad_sql_raises_migration_error(tmp_path):
    """A migration with invalid SQL must raise MigrationError with the filename."""
    db_path = str(tmp_path / "test.db")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(exist_ok=True)
    for src in Path(DEFAULT_MIGRATIONS_DIR).glob("*.sql"):
        (migrations_dir / src.name).write_bytes(src.read_bytes())

    # Add a bad migration after all valid ones (must use version > 4)
    _write_migration(
        migrations_dir,
        "0005_bad_migration.sql",
        "THIS IS NOT VALID SQL AT ALL;",
    )

    with pytest.raises(MigrationError) as exc_info:
        migrate(db_path, migrations_dir=str(migrations_dir))

    assert "0005_bad_migration.sql" in str(exc_info.value)


def test_migrate_bad_sql_leaves_db_at_prior_version(tmp_path):
    """After MigrationError, the DB must remain at the last committed version."""
    db_path = str(tmp_path / "test.db")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    for src in Path(DEFAULT_MIGRATIONS_DIR).glob("*.sql"):
        (migrations_dir / src.name).write_bytes(src.read_bytes())

    # Apply the valid migrations first so we have a baseline of version 4
    migrate(db_path, migrations_dir=str(migrations_dir))
    assert _get_max_version(db_path) == 4

    # Now add the bad migration at version 5 and re-run
    _write_migration(
        migrations_dir,
        "0005_bad_migration.sql",
        "INVALID SQL;",
    )

    with pytest.raises(MigrationError):
        migrate(db_path, migrations_dir=str(migrations_dir))

    # Version must still be 4; the bad migration was rolled back
    assert _get_max_version(db_path) == 4


def test_migrate_bad_sql_does_not_partially_apply(tmp_path):
    """Rollback must prevent partial application of a multi-statement migration."""
    db_path = str(tmp_path / "test.db")
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    for src in Path(DEFAULT_MIGRATIONS_DIR).glob("*.sql"):
        (migrations_dir / src.name).write_bytes(src.read_bytes())

    migrate(db_path, migrations_dir=str(migrations_dir))

    # A migration whose first statement succeeds but second statement fails
    # (must use version 5 so it is pending after all 4 real migrations)
    _write_migration(
        migrations_dir,
        "0005_partial_fail.sql",
        "\n".join([
            "CREATE TABLE rollback_canary (id INTEGER PRIMARY KEY);",
            "THIS STATEMENT IS INVALID SQL;",
        ]),
    )

    with pytest.raises(MigrationError):
        migrate(db_path, migrations_dir=str(migrations_dir))

    # The canary table must not exist — the whole migration was rolled back
    assert "rollback_canary" not in _get_tables(db_path)


def test_migrate_raises_migration_error_for_missing_migrations_dir(tmp_path):
    """migrate() must raise MigrationError when the migrations directory does not exist."""
    db_path = str(tmp_path / "test.db")
    with pytest.raises(MigrationError) as exc_info:
        migrate(db_path, migrations_dir=str(tmp_path / "nonexistent"))
    assert "not found" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 5. Seed integration
# ---------------------------------------------------------------------------

def test_seed_creates_schema_version_table(tmp_path):
    """seed() must produce a schema_version table alongside the alumni table."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    assert "schema_version" in _get_tables(db_path)


def test_seed_with_no_existing_db_produces_versioned_db(tmp_path):
    """A fresh seed must create a fully migrated database at version 4."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    assert _get_max_version(db_path) == 4


def test_seed_with_legacy_db_upgrades_schema(tmp_path):
    """seed() on a legacy database must create schema_version and reach version 4."""
    db_path = str(tmp_path / "alumni.db")
    _make_legacy_db(db_path)
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    assert "schema_version" in _get_tables(db_path)
    assert _get_max_version(db_path) == 4


def test_seed_with_legacy_db_alumni_data_preserved(tmp_path):
    """seed() on a legacy database must upsert alumni data without losing rows."""
    db_path = str(tmp_path / "alumni.db")
    _make_legacy_db(db_path, insert_row=True)
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    # The legacy row (A001) is upserted along with the 6 sample CSV rows.
    # The legacy row has the same alumni_id as A001 in the CSV, so INSERT OR
    # REPLACE replaces it. Total should still be 6 (sample CSV count).
    assert _alumni_count(db_path) == 6


def test_seed_with_already_versioned_db_is_idempotent(tmp_path):
    """Calling seed() twice must leave the database in the same state."""
    db_path = str(tmp_path / "alumni.db")
    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)
    count_after_first = _alumni_count(db_path)
    version_after_first = _get_max_version(db_path)
    rows_after_first = len(_get_version_rows(db_path))

    seed(csv_path=DEFAULT_CSV_PATH, db_path=db_path)

    assert _alumni_count(db_path) == count_after_first
    assert _get_max_version(db_path) == version_after_first
    assert len(_get_version_rows(db_path)) == rows_after_first


# ---------------------------------------------------------------------------
# 6. CLI exit codes
# ---------------------------------------------------------------------------

def test_migrate_cli_exits_0_on_success(tmp_path):
    """migrate_database.py must exit 0 when all migrations apply cleanly."""
    db_path = str(tmp_path / "test.db")
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "execution" / "migrate_database.py"),
            "--db", db_path,
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
    )
    assert result.returncode == 0


def test_migrate_cli_exits_1_on_missing_migrations_dir(tmp_path):
    """migrate_database.py must exit 1 when the migrations directory does not exist."""
    db_path = str(tmp_path / "test.db")
    result = subprocess.run(
        [
            sys.executable,
            str(_REPO_ROOT / "execution" / "migrate_database.py"),
            "--db", db_path,
            "--migrations", str(tmp_path / "nonexistent"),
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
    )
    assert result.returncode == 1
