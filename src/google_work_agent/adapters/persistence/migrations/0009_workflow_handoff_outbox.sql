-- Migration 0009: durable workflow handoff outbox and execution admission.
-- SQLite / UTF-8

BEGIN IMMEDIATE;

CREATE TABLE workflow_handoffs (
    handoff_id TEXT PRIMARY KEY,
    trigger_command_id TEXT NOT NULL UNIQUE CHECK (length(trigger_command_id) BETWEEN 1 AND 255),
    run_id TEXT NOT NULL,
    langgraph_thread_id TEXT NOT NULL CHECK (length(langgraph_thread_id) BETWEEN 1 AND 255),
    graph_profile TEXT NOT NULL CHECK (
        graph_profile IN ('SINGLE_BASELINE', 'THREE_STAGE', 'SIX_ROLE_BASELINE')
    ),
    graph_version TEXT NOT NULL CHECK (length(graph_version) BETWEEN 1 AND 255),
    requested_mode TEXT NOT NULL CHECK (requested_mode IN ('AUTO', 'LOCAL_GPU', 'API_LLM')),
    execution_kind TEXT NOT NULL CHECK (execution_kind IN ('START', 'RESUME')),
    resume_target_json TEXT CHECK (
        resume_target_json IS NULL OR (
            json_valid(resume_target_json)
            AND length(CAST(resume_target_json AS BLOB)) <= 8192
        )
    ),
    checkpoint_id TEXT,
    checkpoint_generation INTEGER NOT NULL CHECK (checkpoint_generation >= 0),
    run_sequence INTEGER NOT NULL CHECK (run_sequence >= 1),
    control_kind TEXT NOT NULL CHECK (
        control_kind IN (
            'NONE', 'CONFIRMATION_RESPONSE', 'CONTEXT_ADJUSTMENT',
            'RETRIEVAL_CACHE_RESTART'
        )
    ),
    control_payload_json TEXT CHECK (
        control_payload_json IS NULL OR (
            json_valid(control_payload_json)
            AND length(CAST(control_payload_json AS BLOB)) <= 32768
        )
    ),
    control_payload_hash TEXT CHECK (
        control_payload_hash IS NULL OR (
            length(control_payload_hash) = 64
            AND control_payload_hash NOT GLOB '*[^0-9a-f]*'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN ('PENDING', 'DISPATCHED', 'CONSUMED', 'BLOCKED_BINDING', 'SUPERSEDED')
    ),
    last_submit_reason TEXT CHECK (
        last_submit_reason IS NULL OR last_submit_reason IN (
            'ALREADY_RUNNING', 'NOT_COMMITTED', 'BINDING_MISMATCH', 'SHUTTING_DOWN'
        )
    ),
    execution_admission_json TEXT CHECK (
        execution_admission_json IS NULL OR (
            json_valid(execution_admission_json)
            AND length(CAST(execution_admission_json AS BLOB)) <= 16384
        )
    ),
    applied_checkpoint_id TEXT,
    applied_checkpoint_generation INTEGER,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    dispatched_at_ms INTEGER CHECK (dispatched_at_ms IS NULL OR dispatched_at_ms >= 0),
    consumed_at_ms INTEGER CHECK (consumed_at_ms IS NULL OR consumed_at_ms >= 0),
    superseded_at_ms INTEGER CHECK (superseded_at_ms IS NULL OR superseded_at_ms >= 0),
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, run_sequence),
    CHECK (
        (execution_kind = 'START' AND checkpoint_id IS NULL
            AND checkpoint_generation = 0 AND resume_target_json IS NULL)
        OR
        (execution_kind = 'RESUME' AND checkpoint_id IS NOT NULL
            AND checkpoint_generation >= 1 AND resume_target_json IS NOT NULL)
    ),
    CHECK (
        (control_kind = 'NONE' AND control_payload_json IS NULL
            AND control_payload_hash IS NULL)
        OR
        (control_kind <> 'NONE' AND control_payload_hash IS NOT NULL
            AND (control_payload_json IS NOT NULL OR status IN ('CONSUMED', 'SUPERSEDED')))
    ),
    CHECK (
        (applied_checkpoint_id IS NULL AND applied_checkpoint_generation IS NULL)
        OR
        (applied_checkpoint_id IS NOT NULL AND applied_checkpoint_generation >= 0)
    ),
    CHECK (status <> 'DISPATCHED' OR dispatched_at_ms IS NOT NULL),
    CHECK (status <> 'CONSUMED' OR consumed_at_ms IS NOT NULL),
    CHECK (status <> 'SUPERSEDED' OR superseded_at_ms IS NOT NULL)
);

CREATE INDEX ix_workflow_handoffs_dispatch_head
    ON workflow_handoffs(run_id, status, run_sequence);
CREATE INDEX ix_workflow_handoffs_redrive
    ON workflow_handoffs(status, created_at_ms, handoff_id);
CREATE INDEX ix_workflow_handoffs_blocked_binding
    ON workflow_handoffs(status, run_id, run_sequence)
    WHERE status = 'BLOCKED_BINDING';

COMMIT;

PRAGMA foreign_key_check;
