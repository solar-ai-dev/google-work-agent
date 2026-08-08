-- Google Work Agent P0 Domain Database Schema v1.3
-- Effect authority expansion: READ / CREATE / UPDATE / SEND / DELETE

PRAGMA foreign_keys = OFF;

CREATE TABLE actions_new (
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
        verification_policy IN ('NONE', 'GET_COMPARE', 'SENT_LOOKUP', 'GET_ABSENT')
    ),
    recovery_policy         TEXT NOT NULL CHECK (
        recovery_policy IN ('NONE', 'GET_TARGET', 'RESOURCE_SEARCH', 'MESSAGE_SEARCH')
    ),
    target_resource_ref_id  TEXT,
    status                  TEXT NOT NULL CHECK (
        status IN (
            'PROPOSED', 'MODIFIED', 'APPROVED', 'REJECTED', 'EXPIRED',
            'EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED',
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
        (
            effect_type = 'READ'
            AND approval_requirement = 'NONE'
            AND verification_policy = 'NONE'
            AND recovery_policy = 'NONE'
        )
        OR
        (
            effect_type = 'CREATE'
            AND approval_requirement = 'REQUIRED'
            AND verification_policy = 'GET_COMPARE'
            AND recovery_policy = 'RESOURCE_SEARCH'
        )
        OR
        (
            effect_type = 'UPDATE'
            AND approval_requirement = 'REQUIRED'
            AND verification_policy = 'GET_COMPARE'
            AND recovery_policy = 'GET_TARGET'
        )
        OR
        (
            effect_type = 'SEND'
            AND approval_requirement = 'REQUIRED'
            AND verification_policy = 'SENT_LOOKUP'
            AND recovery_policy = 'MESSAGE_SEARCH'
        )
        OR
        (
            effect_type = 'DELETE'
            AND approval_requirement = 'REQUIRED'
            AND verification_policy = 'GET_ABSENT'
            AND recovery_policy = 'GET_TARGET'
        )
    )
);

INSERT INTO actions_new (
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

ALTER TABLE actions_new RENAME TO actions;

CREATE INDEX ix_actions_plan_status
    ON actions(plan_id, status, position);

CREATE INDEX ix_actions_recovery
    ON actions(status, updated_at_ms)
    WHERE status IN ('EXECUTING', 'UNKNOWN_RESULT', 'MISMATCH');
