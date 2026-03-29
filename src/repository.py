"""
src/repository.py

Alumni data-access layer: interface, exceptions, and concrete implementations.

AlumniRepository defines the contract all data sources must satisfy.
Current implementations:
    CsvAlumniRepository    — loads from a CSV file (default for local dev)
    SqliteAlumniRepository — loads from a seeded SQLite database

Both return the same list[dict] profile shape used by rank_alumni() in
src/matching_engine.py. Switching implementations requires a one-line change
in the lifespan context manager in src/api.py.

Write operations:
    create_alumni(), update_alumni(), and delete_alumni() are defined on the
    interface and implemented only in SqliteAlumniRepository.
    CsvAlumniRepository raises NotImplementedError — writes require a
    DB-backed deployment (DATABASE_PATH must be set). Each write opens a
    fresh connection so it sees the latest committed state.
"""

from __future__ import annotations

import abc


class AlumniAlreadyExistsError(Exception):
    """
    Raised by create_alumni() or update_alumni() when a uniqueness constraint
    is violated.

    Attributes:
        field — the conflicting field name: "alumni_id" or "email"
        value — the conflicting value supplied by the caller
    """

    def __init__(self, field: str, value: str) -> None:
        self.field = field
        self.value = value
        super().__init__(f"{field} already exists: {value}")


class AlumniNotFoundError(Exception):
    """
    Raised by update_alumni() or delete_alumni() when the target alumni_id
    does not exist in the data store.

    Attributes:
        alumni_id — the identifier that was not found
    """

    def __init__(self, alumni_id: str) -> None:
        self.alumni_id = alumni_id
        super().__init__(f"Alumni not found: {alumni_id}")


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

    @abc.abstractmethod
    def update_alumni(self, alumni_id: str, profile: dict) -> dict:
        """
        Fully replace the mutable fields of an existing alumni profile.

        alumni_id identifies the record to update. profile must contain the
        seven mutable fields (full_name, email, skills, interests, location,
        engagement_score, availability), already normalized. alumni_id must
        not be present in profile.

        Returns the updated profile dict including alumni_id.

        Raises:
            AlumniNotFoundError      — if alumni_id does not exist.
            AlumniAlreadyExistsError — if the new email is held by a different record.
            NotImplementedError      — if the implementation does not support writes.
        """

    @abc.abstractmethod
    def delete_alumni(self, alumni_id: str) -> None:
        """
        Permanently remove the alumni identified by alumni_id.

        Raises:
            AlumniNotFoundError — if alumni_id does not exist.
            NotImplementedError — if the implementation does not support writes.
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

    def update_alumni(self, alumni_id: str, profile: dict) -> dict:
        raise NotImplementedError(
            "CsvAlumniRepository is read-only. "
            "Set DATABASE_PATH to a seeded SQLite database to enable writes."
        )

    def delete_alumni(self, alumni_id: str) -> None:
        raise NotImplementedError(
            "CsvAlumniRepository is read-only. "
            "Set DATABASE_PATH to a seeded SQLite database to enable writes."
        )


class SqliteAlumniRepository(AlumniRepository):
    """
    Alumni repository backed by a seeded SQLite database.

    Profiles are loaded once at construction and held in memory,
    matching the startup-load behaviour of the CSV path.

    create_alumni() and update_alumni() each open a fresh connection per call
    so writes see the latest committed state. After a successful write the
    in-memory cache is updated so subsequent reads reflect the change without
    requiring a restart.

    Cache and app.state.profiles share the same list object (assigned once at
    startup via repo.get_all_alumni()). In-place mutations to self._profiles
    are immediately visible to _get_profiles() and rank_alumni().
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
            alumni_id,  # WHERE clause
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
            # The only UPDATE constraint that can fire is the email UNIQUE index.
            # alumni_id is not being changed so its uniqueness cannot be violated.
            raise AlumniAlreadyExistsError("email", profile["email"]) from exc
        finally:
            con.close()

        # Replace the matching element in the in-memory cache in place.
        updated = {"alumni_id": alumni_id, **profile}
        for i, p in enumerate(self._profiles):
            if p["alumni_id"] == alumni_id:
                self._profiles[i] = updated
                break
        return updated

    def delete_alumni(self, alumni_id: str) -> None:
        import sqlite3 as _sqlite3

        con = _sqlite3.connect(self._db_path)
        try:
            cursor = con.execute(
                "DELETE FROM alumni WHERE alumni_id = ?", (alumni_id,)
            )
            con.commit()
        finally:
            con.close()

        if cursor.rowcount == 0:
            raise AlumniNotFoundError(alumni_id)

        # Rebuild the in-memory cache without the deleted profile.
        # List comprehension produces a new list object; the API route
        # is responsible for re-syncing app.state.profiles via
        # repo.get_all_alumni() after this method returns.
        self._profiles = [p for p in self._profiles if p["alumni_id"] != alumni_id]
