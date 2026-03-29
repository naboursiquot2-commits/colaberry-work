"""
execution/seed_database.py

Seeds the SQLite alumni database from the CSV source file.

What it does:
    1. Calls migrate_database.migrate() to bring the schema to the latest
       version (creates tables on first run; upgrades legacy databases)
    2. Reads data/sample_alumni.csv (or a custom CSV path)
    3. Upserts every row using INSERT OR REPLACE

Idempotency guarantee:
    INSERT OR REPLACE INTO alumni replaces any existing row with the same
    alumni_id (primary key). Running this script multiple times always
    produces the same final database state: same row count, same values.

Normalization applied (identical to load_alumni_profiles_csv):
    - skills and interests: comma-split, lowercase, strip whitespace, stored
      as a JSON array (e.g. '["python","sql"]')
    - engagement_score: parsed as float; "N/A" and blank values become 0.0;
      values > 1.0 are treated as 0–100 scale and divided by 100

Run:
    python execution/seed_database.py
    python execution/seed_database.py --csv data/sample_alumni.csv --db data/alumni.db
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV_PATH = str(_REPO_ROOT / "data" / "sample_alumni.csv")
DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "alumni.db")


_UPSERT = """
INSERT OR REPLACE INTO alumni
    (alumni_id, full_name, email, skills, interests,
     location, engagement_score, availability)
VALUES (?, ?, ?, ?, ?, ?, ?, ?);
"""


# ---------------------------------------------------------------------------
# Normalization helpers (mirrors load_alumni_profiles_csv behavior exactly)
# ---------------------------------------------------------------------------

def _parse_list(raw: str) -> list[str]:
    """Split a comma-separated string into a lowercase, stripped list."""
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _parse_engagement(raw: str) -> float:
    """
    Parse engagement_score from a raw CSV string.
    - Blank or non-numeric (e.g. "N/A") → 0.0
    - Numeric value > 1.0 treated as 0–100 scale → divided by 100
    """
    raw = (raw or "").strip()
    try:
        value = float(raw) if raw else 0.0
    except ValueError:
        value = 0.0
    if value > 1.0:
        value = value / 100.0
    return value


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

def seed(csv_path: str = DEFAULT_CSV_PATH, db_path: str = DEFAULT_DB_PATH) -> int:
    """
    Seed the SQLite database at db_path from the CSV at csv_path.

    Runs schema migrations first to ensure the database is at the latest
    version, then upserts every row from the CSV. Returns the number of
    rows upserted.

    Idempotent: safe to call multiple times. Each call produces the same
    final database state.
    """
    if not Path(csv_path).exists():
        raise FileNotFoundError(f"CSV source not found: {csv_path}")

    # Ensure the schema is current before writing data.
    # The try/except handles both module-import (execution.migrate_database)
    # and script-execution (migrate_database on sys.path) contexts.
    try:
        from execution.migrate_database import migrate as _migrate
    except ImportError:
        from migrate_database import migrate as _migrate  # type: ignore[no-redef]
    _migrate(db_path)

    con = sqlite3.connect(db_path)
    try:
        count = 0

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                con.execute(
                    _UPSERT,
                    (
                        (row.get("alumni_id") or "").strip(),
                        (row.get("full_name") or "").strip(),
                        (row.get("email") or "").strip(),
                        json.dumps(_parse_list(row.get("skills") or "")),
                        json.dumps(_parse_list(row.get("interests") or "")),
                        (row.get("location") or "").strip(),
                        _parse_engagement(row.get("engagement_score") or ""),
                        (row.get("availability") or "").strip(),
                    ),
                )
                count += 1

        con.commit()
    finally:
        con.close()

    return count


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the SQLite alumni database from the CSV source."
    )
    parser.add_argument(
        "--csv",
        default=DEFAULT_CSV_PATH,
        help=f"Path to the alumni CSV file (default: {DEFAULT_CSV_PATH})",
    )
    parser.add_argument(
        "--db",
        default=DEFAULT_DB_PATH,
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH})",
    )
    args = parser.parse_args()

    print(f"CSV source : {args.csv}")
    print(f"DB target  : {args.db}")

    try:
        count = seed(csv_path=args.csv, db_path=args.db)
    except FileNotFoundError as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"Seeded {count} row(s) — idempotent upsert complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
