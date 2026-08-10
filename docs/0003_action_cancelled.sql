-- Google Work Agent P0 Domain Database Schema v1.4
-- Migration 0003: add CANCELLED Action status
-- SQLite / UTF-8
--
-- Preconditions:
--   * 0001_initial.sql and 0002_action_effect_send_delete.sql have been applied.
--   * Migration runner owns checksum/schema_migrations bookkeeping.
--   * No external Google/MCP/LLM call may run while this migration is active.
--
-- Rationale:
--   Runtime cancel contract requires unstarted/pending Actions to transition to CANCELLED.
--   No Effect/verification/recovery mapping changes are introduced by this migration.

PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

CREATE TABLE actions__v1_4 (
    id                      TEXT PRIMARY KEY,
    plan_id                 TEXT NOT NULL,
    position                INTEGER NOT NULL CHECK (position >= 1),
    tool_name               TEXT NOT NULL CHECK (length(tool_name) BETWEEN 1 AND 100),
    effect_type             TEXT NOT NULL CHECK (
        effect_type IN ('READ', 'CREATE', 'UPDATE', 'SEND', 'DELETE')
    ),
    approval_requirement    TEXT NOT NULL CHECK (
        approval_requirement IN ('NONE', 'REQUIRED')
    ),
    verification_policy     TEXT NOT NULL CHECK (
        verification_policy IN ('NONE', 'GET_COMPARE', 'GET_ABSENT', 'SENT_LOOKUP')
    ),
    recovery_policy         TEXT NOT NULL CHECK (
        recovery_policy IN ('NONE', 'GET_TARGET', 'RESOURCE_SEARCH', 'MESSAGE_SEARCH')
    ),
    target_resource_ref_id  TEXT,
    status                  TEXT NOT NULL CHECK (
        status IN (
            'PROPOSED', 'MODIFIED', 'APPROVED', 'REJECTED', 'EXPIRED',
            'CANCELLED', 'EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED',
            'FAILED', 'BLOCKED', 'DEPENDENCY_BLOCKED', 'MISMATCH'
        )
    ),
    arguments_json          TEXT NOT NULL CHECK (
        json_valid(arguments_json)
        AND length(CAST(arguments_json AS BLOB)) <= 65536
    ),
    arguments_hash          TEXT NOT NULL CHECK (length(arguments_hash) = 64),
    expected_json           TEXT NOT NULL CHECK (
        json_valid(expected_json)
        AND length(CAST(expected_json AS BLOB)) <= 65536
    ),
    risk_json               TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(risk_json)
        AND length(CAST(risk_json AS BLOB)) <= 16384
    ),
    version                 INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at_ms           INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms           INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    FOREIGN KEY (target_resource_ref_id)
        REFERENCES resource_refs(id) ON DELETE SET NULL,
    UNIQUE (plan_id, position),
    CHECK (
        (effect_type = 'READ' AND approval_requirement = 'NONE' AND verification_policy = 'NONE' AND recovery_policy = 'NONE')
        OR (effect_type = 'CREATE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_COMPARE' AND recovery_policy = 'RESOURCE_SEARCH')
        OR (effect_type = 'UPDATE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_COMPARE' AND recovery_policy = 'GET_TARGET')
        OR (effect_type = 'SEND' AND approval_requirement = 'REQUIRED' AND verification_policy = 'SENT_LOOKUP' AND recovery_policy = 'MESSAGE_SEARCH')
        OR (effect_type = 'DELETE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_ABSENT' AND recovery_policy = 'GET_TARGET')
    )
);

INSERT INTO actions__v1_4 (
    id, plan_id, position, tool_name, effect_type, approval_requirement,
    verification_policy, recovery_policy, target_resource_ref_id, status,
    arguments_json, arguments_hash, expected_json, risk_json, version,
    created_at_ms, updated_at_ms
)
SELECT
    id, plan_id, position, tool_name, effect_type, approval_requirement,
    verification_policy, recovery_policy, target_resource_ref_id, status,
    arguments_json, arguments_hash, expected_json, risk_json, version,
    created_at_ms, updated_at_ms
FROM actions;

DROP TABLE actions;
ALTER TABLE actions__v1_4 RENAME TO actions;

CREATE INDEX ix_actions_plan_status
    ON actions(plan_id, status, position);

CREATE INDEX ix_actions_recovery
    ON actions(status, updated_at_ms)
    WHERE status IN ('UNKNOWN_RESULT', 'MISMATCH', 'FAILED');

COMMIT;
PRAGMA foreign_keys = ON;

-- Migration runner must fail the migration/release if this returns any rows.
PRAGMA foreign_key_check;
