-- Migration 0012: retain RecoveryContext version history across physical clear.
-- SQLite / UTF-8

BEGIN IMMEDIATE;

CREATE TABLE recovery_context_tombstones (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    last_version INTEGER NOT NULL CHECK (last_version >= 0),
    cleared_at_ms INTEGER NOT NULL CHECK (cleared_at_ms >= 0)
);

COMMIT;

PRAGMA foreign_key_check;
