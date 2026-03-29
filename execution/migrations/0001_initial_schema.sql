-- Migration 0001: initial_schema
-- Creates the alumni table that backs all read and write operations.
-- Uses CREATE TABLE IF NOT EXISTS so this migration is safe to re-run
-- against a database that already has the table (idempotent).

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
