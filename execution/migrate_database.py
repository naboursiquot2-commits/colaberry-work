"""
execution/migrate_database.py

SQLite schema migration runner for the alumni database.

How it works:
    1. Ensures a schema_version table exists (bootstrap on first run or when
       applied to a legacy pre-migration database).
    2. Reads the current schema version: MAX(version) from schema_version,
       or 0 if the table is empty.
    3. Discovers all *.sql files in the migrations directory whose numeric
       prefix is greater than the current version.
    4. Applies each pending migration in ascending version order, each in its
       own explicit SQLite transaction.
    5. Inserts a row into schema_version after each successful commit.
    6. On failure: rolls back the current migration and raises MigrationError
       with the filename included in the message. The database is left at the
       last successfully committed version.

Bootstrap logic for existing databases:
    If schema_version does not exist but the alumni table does, the database
    was created by a pre-migration version of seed_database.py. The runner
    creates schema_version and records migrations 0001 and 0002 as
    bootstrapped (their DDL was already applied). This brings the version
    counter to 2 without re-running any DDL.

Run:
    python execution/migrate_database.py
    python execution/migrate_database.py --db data/alumni.db
    python execution/migrate_database.py --db /custom/path/alumni.db --migrations execution/migrations
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = str(_REPO_ROOT / "execution" / "migrations")
DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "alumni.db")

# The schema_version table DDL, used during bootstrap.
_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    description TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
)
"""

# Highest migration version that is guaranteed to be present when a legacy
# database (alumni table exists, no schema_version) is bootstrapped.
# Update this constant whenever new migrations are added to ensure legacy
# databases are correctly stamped on their first upgrade.
_BOOTSTRAP_VERSION = 2


# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class MigrationError(Exception):
    """
    Raised when a migration cannot be applied.

    Attributes:
        filename — the migration filename (or "(setup)" for bootstrap errors)
        reason   — the underlying error message
    """

    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"Migration {filename!r} failed: {reason}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_table_names(con: sqlite3.Connection) -> set[str]:
    """Return the set of table names currently in the database."""
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


def _get_current_version(con: sqlite3.Connection) -> int:
    """
    Return the highest version number recorded in schema_version, or 0 if
    the table is empty.  Assumes schema_version already exists.
    """
    row = con.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version"
    ).fetchone()
    return row[0]


def _parse_sql_statements(sql: str) -> list[str]:
    """
    Split a SQL string into a list of individual executable statements.

    Strips line comments (-- ...) and blank lines before splitting on
    semicolons. Each returned statement is stripped of surrounding whitespace.

    Note: this parser is intentionally simple and sufficient for DDL files
    that do not contain semicolons inside string literals or block comments.
    """
    lines = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            lines.append(stripped)
    joined = " ".join(lines)
    return [stmt.strip() for stmt in joined.split(";") if stmt.strip()]


def _discover_migrations(migrations_dir: str) -> list[tuple[int, str, str]]:
    """
    Return (version, description, filepath) for all valid *.sql files in
    migrations_dir, sorted ascending by version number.

    Valid filenames have the form: NNNN_description.sql where NNNN is a
    numeric prefix. Files that do not match this pattern are silently skipped.
    """
    migrations_path = Path(migrations_dir)
    if not migrations_path.is_dir():
        raise MigrationError(
            "(setup)",
            f"Migrations directory not found: {migrations_dir}",
        )

    results = []
    for path in sorted(migrations_path.glob("*.sql")):
        stem = path.stem  # e.g. "0001_initial_schema"
        parts = stem.split("_", 1)
        if len(parts) < 2 or not parts[0].isdigit():
            continue  # skip malformed filename; do not raise
        version = int(parts[0])
        description = parts[1]
        results.append((version, description, str(path)))
    return results


def _bootstrap(con: sqlite3.Connection) -> None:
    """
    Ensure the schema_version table exists.

    If schema_version is absent but the alumni table is already present, the
    database predates migration support. The bootstrap records all migrations
    up to _BOOTSTRAP_VERSION as applied so that the runner does not attempt
    to re-execute their DDL (which uses CREATE TABLE IF NOT EXISTS and is
    safe to re-run, but is unnecessary).

    If neither table exists, schema_version is created empty and the runner
    will apply all migrations from version 1 upward.

    The entire bootstrap runs in a single transaction; if any step fails the
    database is rolled back to its prior state.
    """
    table_names = _get_table_names(con)
    if "schema_version" in table_names:
        return  # already bootstrapped; nothing to do

    try:
        con.execute("BEGIN")
        con.execute(_SCHEMA_VERSION_DDL)

        if "alumni" in table_names:
            # Legacy database: alumni table was created by the old seed script.
            # Record that all migrations up to _BOOTSTRAP_VERSION are applied
            # without re-executing their DDL.
            con.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (1, "bootstrapped: initial_schema"),
            )
            con.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                (2, "bootstrapped: add_schema_version_table"),
            )
        # If alumni does not exist, leave schema_version empty (version = 0)
        # and let the runner apply all migrations from 0001 upward.

        con.execute("COMMIT")
    except Exception as exc:
        try:
            con.execute("ROLLBACK")
        except Exception:
            pass
        raise MigrationError("(bootstrap)", str(exc)) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def migrate(
    db_path: str = DEFAULT_DB_PATH,
    migrations_dir: str = DEFAULT_MIGRATIONS_DIR,
) -> int:
    """
    Apply all pending migrations to the SQLite database at db_path.

    Returns the final schema version as an integer (>= 0).  If the database
    is already at the latest version, returns the current version immediately.

    Each migration runs in its own explicit SQLite transaction.  On failure
    the current migration is rolled back and MigrationError is raised; the
    database is left at the last successfully committed version.

    Raises:
        MigrationError — if bootstrap fails or any migration cannot be applied.
    """
    con = sqlite3.connect(db_path)
    con.isolation_level = None  # autocommit; we use explicit BEGIN/COMMIT/ROLLBACK

    try:
        _bootstrap(con)
        current_version = _get_current_version(con)
        all_migrations = _discover_migrations(migrations_dir)
        pending = [
            (v, d, p) for v, d, p in all_migrations if v > current_version
        ]

        for version_num, description, filepath in pending:
            filename = Path(filepath).name
            sql = Path(filepath).read_text(encoding="utf-8")
            statements = _parse_sql_statements(sql)

            try:
                con.execute("BEGIN")
                for stmt in statements:
                    con.execute(stmt)
                con.execute(
                    "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                    (version_num, description),
                )
                con.execute("COMMIT")
            except Exception as exc:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                raise MigrationError(filename, str(exc)) from exc

        return _get_current_version(con)

    finally:
        con.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply pending SQLite schema migrations."
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--migrations",
        default=DEFAULT_MIGRATIONS_DIR,
        help=f"Path to the migrations directory (default: {DEFAULT_MIGRATIONS_DIR})",
    )
    args = parser.parse_args()

    print(f"Database   : {args.db}")
    print(f"Migrations : {args.migrations}")

    try:
        final_version = migrate(db_path=args.db, migrations_dir=args.migrations)
    except MigrationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1

    print(f"Schema version: {final_version} — up to date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
