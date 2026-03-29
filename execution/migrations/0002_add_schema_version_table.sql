-- Migration 0002: add_schema_version_table
-- Creates the schema_version table used to track which migrations have been
-- applied. One row is inserted per migration by the runner itself after
-- the migration SQL commits successfully.
-- Uses CREATE TABLE IF NOT EXISTS so this migration is idempotent: if the
-- bootstrap logic already created the table (legacy database path), this
-- is a no-op and only the version row is inserted.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    description TEXT    NOT NULL,
    applied_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
