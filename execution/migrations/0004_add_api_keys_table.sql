-- Migration 0004: add api_keys table
-- Each row represents one issued API key.  Plaintext keys are never stored.
-- key_prefix holds the first segment of the raw key for O(1) prefix lookup.
-- key_hash stores "{hex_salt}:{hex_digest}" produced by hashlib.scrypt.

CREATE TABLE IF NOT EXISTS api_keys (
    key_id       TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id),
    key_prefix   TEXT NOT NULL UNIQUE,
    key_hash     TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    is_active    INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    expires_at   TEXT
);
