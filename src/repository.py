"""
src/repository.py

Alumni data-access layer: interface and concrete implementations.

AlumniRepository defines the read contract all data sources must satisfy.
Current implementations:
    CsvAlumniRepository    — loads from a CSV file (default for local dev)
    SqliteAlumniRepository — loads from a seeded SQLite database

Both return the same list[dict] profile shape used by rank_alumni() in
src/matching_engine.py. Switching between implementations requires a
one-line change in the lifespan context manager in src/api.py.

Extending for future write operations:
    Add create_alumni(), update_alumni(), delete_alumni() to AlumniRepository.
    Implement them in SqliteAlumniRepository using a fresh connection per call
    (so writes see the latest committed state without invalidating the cache).
    Raise NotImplementedError in CsvAlumniRepository — writes require a DB.
    The API layer calls repo methods; no SQL ever leaks into route handlers.
"""

from __future__ import annotations

import abc


class AlumniRepository(abc.ABC):
    """Abstract base: the data-access contract for alumni profiles."""

    @abc.abstractmethod
    def get_all_alumni(self) -> list[dict]:
        """Return all alumni profiles as a list of dicts."""

    @abc.abstractmethod
    def get_alumni_by_id(self, alumni_id: str) -> dict | None:
        """Return a single profile by alumni_id, or None if not found."""


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


class SqliteAlumniRepository(AlumniRepository):
    """
    Alumni repository backed by a seeded SQLite database.

    Profiles are loaded once at construction and held in memory,
    matching the startup-load behaviour of the CSV path.

    db_path is retained so future write methods (create_alumni,
    update_alumni, delete_alumni) can open a new connection per operation
    and see the latest committed state without re-caching the profile list.
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
