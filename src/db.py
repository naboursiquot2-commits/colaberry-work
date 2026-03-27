"""
src/db.py

Database access layer for the alumni SQLite store.

This module is intentionally minimal: it is the only place in the codebase
that opens a database connection or issues SQL. The matching engine and API
layer receive the same list[dict] profile shape whether data was loaded from
CSV or from the database.

Output contract:
    load_alumni_profiles_db() returns list[dict] with the exact same field
    names and value types as load_alumni_profiles_csv() in src/matching_engine.py.
    The two functions are interchangeable as inputs to rank_alumni().
"""

from __future__ import annotations

import json
import sqlite3


def _row_to_profile(row: sqlite3.Row) -> dict:
    """
    Convert a sqlite3.Row from the alumni table into a profile dict.

    skills and interests are stored as JSON arrays in the DB and are
    deserialized back into Python lists here.

    engagement_score is stored pre-normalized (0.0–1.0) by the seed script;
    no further transformation is needed.
    """
    return {
        "alumni_id": row["alumni_id"],
        "full_name": row["full_name"],
        "email": row["email"],
        "skills": json.loads(row["skills"]),
        "interests": json.loads(row["interests"]),
        "location": row["location"],
        "engagement_score": row["engagement_score"],
        "availability": row["availability"],
    }


def load_alumni_profiles_db(db_path: str) -> list[dict]:
    """
    Load all alumni profiles from the SQLite database at db_path.

    Returns a list of profile dicts ordered by alumni_id. The dict structure
    is identical to the output of load_alumni_profiles_csv() and is the
    expected input format for rank_alumni().

    Raises FileNotFoundError if db_path does not exist.
    Raises sqlite3.OperationalError if the alumni table has not been created
    (i.e. the database has not been seeded via execution/seed_database.py).
    """
    import os
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database file not found: {db_path}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT alumni_id, full_name, email, skills, interests, "
            "location, engagement_score, availability "
            "FROM alumni ORDER BY alumni_id"
        ).fetchall()
        return [_row_to_profile(row) for row in rows]
    finally:
        con.close()
