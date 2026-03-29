"""
src/repository.py

Alumni data-access layer: interface, exception, and concrete implementations.

AlumniRepository defines the contract all data sources must satisfy.
Current implementations:
    CsvAlumniRepository    — loads from a CSV file (default for local dev)
    SqliteAlumniRepository — loads from a seeded SQLite database

Both return the same list[dict] profile shape used by rank_alumni() in
src/matching_engine.py. Switching implementations requires a one-line change
in the lifespan context manager in src/api.py.

Write operations:
    create_alumni() is defined on the interface and implemented only in
    SqliteAlumniRepository. CsvAlumniRepository raises NotImplementedError —
    writes require a DB-backed deployment (DATABASE_PATH must be set).
    Each write opens a fresh connection so it sees the latest committed state.
"""

from __future__ import annotations

import abc


class AlumniAlreadyExistsError(Exception):
    """
    Raised by create_alumni() when a uniqueness constraint is violated.

    Attributes:
        field — the conflicting field name: "alumni_id" or "email"
        value — the conflicting value supplied by the caller
    """

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} already exists: {value}")


class AlumniRepository(abc.ABC):
    """Abstract base: the data-access contract for alumni profiles."""

    @abc.abstractmethod
    def get_all_alumni(self) -> list[dict]:
        """Return all alumni profiles as a list of dicts."""

    @abc.abstractmethod
    def get_alumni_by_id(self, alumni_id: str) -> dict | None:
        """Return a single profile by alumni_id, or None if not found."""

    @abc.abstractmethod
    def create_alumni(self, profile: dict) -> dict:
        """
        Persist a new alumni profile.

        profile must contain all eight required fields with values already
        normalized: skills and interests as list[str] (lowercase, stripped),
        engagement_score as float 0.0–1.0.

        Returns the created profile dict (same shape as get_all_alumni() items).

        Raises:
            AlumniAlreadyExistsError — if alumni_id or email already exists.
            NotImplementedError      — if the implementation does not support writes.
        """


class CsvAlumniRepository(AlumniRepository):
    """
    Alumni repository backed by a CSV file.

    Profiles are loaded once at construction and held in memory,
    matching the existing startup-load behaviour in src/api.py.

    Write operations are not supported; use SqliteAlumniRepository for writes.
    """

    def __init__(self, csv_path: str) -> None:
        from src.matching_engine import load_alumni_profiles_csv
        self._profiles: list[dict] = load_alumni_profiles_csv(csv_path)

    def get_all_alumni(self) -> list[dict]:
        return self._profiles

    def get_alumni_by_id(self, alumni_id: str) -> dict | None:
        return next(
            (p for p in self._profiles if p["alumni_id"] == alumni_id), None
        )

    def create_alumni(self, profile: dict) -> dict:
        raise NotImplementedError(
            "CsvAlumniRepository is read-only. "
            "Set DATABASE_PATH to a seeded SQLite database to enable writes."
        )


class SqliteAlumniRepository(AlumniRepository):
    """
    Alumni repository backed by a seeded SQLite database.

    Profiles are loaded once at construction and held in memory,
    matching the startup-load behaviour of the CSV path.

    create_alumni() opens a fresh connection per call so writes see the
    latest committed state. After a successful insert the in-memory cache
    is updated so subsequent get_all_alumni() and get_alumni_by_id() calls
    reflect the new profile without requiring a restart.
    """

    def __init__(self, db_path: str) -> None:
        from src.db import load_alumni_profiles_db
        self._db_path = db_path
        self._profiles: list[dict] = load_alumni_profiles_db(db_path)

    def get_all_alumni(self) -> list[dict]:
        return self._profiles

    def get_alumni_by_id(self, alumni_id: str) -> dict | None:
        return next(
            (p for p in self._profiles if p["alumni_id"] == alumni_id), None
        )

    def create_alumni(self, profile: dict) -> dict:
        import json
        import sqlite3 as _sqlite3

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
        con = _sqlite3.connect(self._db_path)
        try:
            con.execute(
                "INSERT INTO alumni "
                "(alumni_id, full_name, email, skills, interests, "
                "location, engagement_score, availability) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            con.commit()
        except _sqlite3.IntegrityError as exc:
            msg = str(exc)
            if "alumni.email" in msg:
                raise AlumniAlreadyExistsError("email", profile["email"]) from exc
            if "alumni.alumni_id" in msg or "alumni_id" in msg:
                raise AlumniAlreadyExistsError("alumni_id", profile["alumni_id"]) from exc
            raise  # unexpected constraint — surface the original error
        finally:
            con.close()

        # Update the in-memory cache so reads immediately see the new profile.
        created = dict(profile)
        self._profiles.append(created)
        return created
