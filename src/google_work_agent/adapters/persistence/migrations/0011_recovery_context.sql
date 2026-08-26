-- Migration 0011: durable RecoveryContextV1 authority (04-A State Transition
-- Contract SS RecoveryContextV1 closed contract).
-- SQLite / UTF-8

BEGIN IMMEDIATE;

CREATE TABLE recovery_contexts (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    reason TEXT NOT NULL CHECK (
        reason IN (
            'UNKNOWN_RESULT', 'VERIFICATION_MISMATCH', 'CHECKPOINT_MISMATCH', 'CONTRACT_VIOLATION'
        )
    ),
    scope TEXT NOT NULL CHECK (scope IN ('RUN', 'ACTION')),
    action_id TEXT CHECK (
        (scope = 'ACTION' AND action_id IS NOT NULL)
        OR (scope = 'RUN' AND action_id IS NULL)
    ),
    execution_attempt_id TEXT,
    verification_id TEXT,
    pre_recovery_status TEXT NOT NULL,
    registered_resume_target_json TEXT CHECK (
        registered_resume_target_json IS NULL OR (
            json_valid(registered_resume_target_json)
            AND length(CAST(registered_resume_target_json AS BLOB)) <= 8192
        )
    ),
    recovery_fingerprint TEXT NOT NULL CHECK (length(recovery_fingerprint) BETWEEN 1 AND 255),
    observed_external_state_fingerprint TEXT,
    verification_input_fingerprint TEXT,
    contract_or_checkpoint_fingerprint TEXT,
    last_recheck_input_hash TEXT,
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= 0)
);

CREATE INDEX ix_recovery_contexts_reason ON recovery_contexts(reason, created_at_ms);

COMMIT;

PRAGMA foreign_key_check;
