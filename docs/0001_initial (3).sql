-- Google Work Agent P0 Domain Database Schema v1.2
-- SQLite / UTF-8
--
-- Connection initialization:
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA busy_timeout = 5000;

CREATE TABLE schema_migrations (
    version         INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    checksum        TEXT NOT NULL CHECK (length(checksum) = 64),
    applied_at_ms   INTEGER NOT NULL CHECK (applied_at_ms >= 0)
);



CREATE TABLE command_receipts (
    command_id          TEXT PRIMARY KEY,
    command_type        TEXT NOT NULL CHECK (length(command_type) BETWEEN 1 AND 100),
    request_hash        TEXT NOT NULL CHECK (length(request_hash) = 64),
    aggregate_type      TEXT NOT NULL CHECK (length(aggregate_type) BETWEEN 1 AND 50),
    aggregate_id        TEXT,
    status              TEXT NOT NULL CHECK (status IN ('RECEIVED', 'APPLIED', 'REJECTED')),
    result_code         TEXT,
    result_version      INTEGER CHECK (result_version IS NULL OR result_version >= 0),
    response_json       TEXT CHECK (
        response_json IS NULL OR (
            json_valid(response_json)
            AND length(CAST(response_json AS BLOB)) <= 65536
        )
    ),
    created_at_ms       INTEGER NOT NULL CHECK (created_at_ms >= 0),
    completed_at_ms     INTEGER CHECK (
        completed_at_ms IS NULL OR completed_at_ms >= created_at_ms
    ),
    CHECK (
        (status = 'RECEIVED' AND completed_at_ms IS NULL)
        OR (status IN ('APPLIED', 'REJECTED') AND completed_at_ms IS NOT NULL)
    )
);

CREATE INDEX ix_command_receipts_created
    ON command_receipts(created_at_ms DESC, command_id);

CREATE INDEX ix_command_receipts_aggregate
    ON command_receipts(aggregate_type, aggregate_id, created_at_ms DESC)
    WHERE aggregate_id IS NOT NULL;

CREATE TABLE google_accounts (
    id                  TEXT PRIMARY KEY,
    email               TEXT NOT NULL COLLATE NOCASE UNIQUE,
    display_name        TEXT,
    connected_at_ms     INTEGER NOT NULL CHECK (connected_at_ms >= 0),
    disconnected_at_ms  INTEGER CHECK (
        disconnected_at_ms IS NULL OR disconnected_at_ms >= connected_at_ms
    )
);

CREATE TABLE conversations (
    id              TEXT PRIMARY KEY,
    account_id      TEXT NOT NULL,
    title           TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms   INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms),
    FOREIGN KEY (account_id) REFERENCES google_accounts(id) ON DELETE RESTRICT
);

CREATE TABLE runs (
    id                   TEXT PRIMARY KEY,
    conversation_id      TEXT NOT NULL,
    entry_mode           TEXT NOT NULL CHECK (
        entry_mode IN ('AGENT_SEARCH', 'RESOURCE_SELECTED')
    ),
    status               TEXT NOT NULL CHECK (
        status IN (
            'CREATED', 'ANALYZING', 'RETRIEVING',
            'WAITING_CONFIRMATION', 'PLANNING', 'WAITING_APPROVAL',
            'EXECUTING', 'VERIFYING', 'COMPLETED',
            'CANCEL_REQUESTED', 'CANCELLED', 'REAUTH_REQUIRED',
            'RECOVERY_REQUIRED', 'FAILED', 'BLOCKED'
        )
    ),
    langgraph_thread_id  TEXT NOT NULL UNIQUE,
    requested_mode       TEXT NOT NULL CHECK (
        requested_mode IN ('AUTO', 'LOCAL_GPU', 'API_LLM')
    ),
    actual_runtime       TEXT CHECK (
        actual_runtime IS NULL
        OR actual_runtime IN ('LOCAL_GPU', 'API_LLM', 'MIXED')
    ),
    budget_json          TEXT NOT NULL CHECK (
        json_valid(budget_json)
        AND length(CAST(budget_json AS BLOB)) <= 16384
    ),
    version              INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    started_at_ms        INTEGER NOT NULL CHECK (started_at_ms >= 0),
    finished_at_ms       INTEGER CHECK (
        finished_at_ms IS NULL OR finished_at_ms >= started_at_ms
    ),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX uq_runs_one_open_per_conversation
    ON runs(conversation_id)
    WHERE finished_at_ms IS NULL;

CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL,
    run_id            TEXT,
    role              TEXT NOT NULL CHECK (
        role IN ('USER', 'ASSISTANT', 'SYSTEM')
    ),
    content           TEXT NOT NULL CHECK (
        length(CAST(content AS BLOB)) <= 65536
    ),
    created_at_ms     INTEGER NOT NULL CHECK (created_at_ms >= 0),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE SET NULL
);

CREATE TABLE plans (
    id              TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    revision_no     INTEGER NOT NULL CHECK (revision_no >= 1),
    status          TEXT NOT NULL CHECK (
        status IN (
            'DRAFT', 'WAITING_APPROVAL', 'ACTIVE',
            'SUPERSEDED', 'CANCELLED', 'COMPLETED'
        )
    ),
    summary_text    TEXT,
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, revision_no)
);

CREATE TABLE resource_refs (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    source              TEXT NOT NULL CHECK (
        source IN ('GMAIL', 'TASKS', 'CALENDAR')
    ),
    resource_type       TEXT NOT NULL CHECK (
        resource_type IN (
            'THREAD', 'MESSAGE', 'TASK', 'EVENT',
            'TASK_LIST', 'CALENDAR'
        )
    ),
    resource_id         TEXT NOT NULL,
    parent_resource_id  TEXT,
    canonical_url       TEXT,
    title               TEXT,
    event_time_ms       INTEGER,
    version_token       TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(metadata_json)
        AND length(CAST(metadata_json AS BLOB)) <= 32768
    ),
    captured_at_ms      INTEGER NOT NULL CHECK (captured_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, source, resource_type, resource_id)
);

CREATE TABLE actions (
    id                      TEXT PRIMARY KEY,
    plan_id                 TEXT NOT NULL,
    position                INTEGER NOT NULL CHECK (position >= 1),
    tool_name               TEXT NOT NULL CHECK (length(tool_name) BETWEEN 1 AND 100),
    effect_type             TEXT NOT NULL CHECK (
        effect_type IN ('READ', 'CREATE', 'UPDATE')
    ),
    approval_requirement    TEXT NOT NULL CHECK (
        approval_requirement IN ('NONE', 'REQUIRED')
    ),
    verification_policy     TEXT NOT NULL CHECK (
        verification_policy IN ('NONE', 'GET_COMPARE')
    ),
    recovery_policy         TEXT NOT NULL CHECK (
        recovery_policy IN ('NONE', 'GET_TARGET', 'RESOURCE_SEARCH')
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
    )
);

CREATE TABLE action_dependencies (
    action_id             TEXT NOT NULL,
    depends_on_action_id  TEXT NOT NULL,
    PRIMARY KEY (action_id, depends_on_action_id),
    CHECK (action_id <> depends_on_action_id),
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_action_id) REFERENCES actions(id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE evidence (
    id                TEXT PRIMARY KEY,
    run_id            TEXT NOT NULL,
    origin_type       TEXT NOT NULL CHECK (
        origin_type IN ('GOOGLE_RESOURCE', 'USER_MESSAGE', 'DERIVED')
    ),
    resource_ref_id   TEXT,
    message_id        TEXT,
    kind              TEXT NOT NULL CHECK (length(kind) BETWEEN 1 AND 50),
    excerpt           TEXT NOT NULL CHECK (
        length(CAST(excerpt AS BLOB)) <= 8192
    ),
    locator_json      TEXT CHECK (
        locator_json IS NULL
        OR (
            json_valid(locator_json)
            AND length(CAST(locator_json AS BLOB)) <= 16384
        )
    ),
    created_at_ms     INTEGER NOT NULL CHECK (created_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (resource_ref_id) REFERENCES resource_refs(id) ON DELETE CASCADE,
    FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE,
    CHECK (
        (
            origin_type = 'GOOGLE_RESOURCE'
            AND resource_ref_id IS NOT NULL
            AND message_id IS NULL
        )
        OR
        (
            origin_type = 'USER_MESSAGE'
            AND resource_ref_id IS NULL
            AND message_id IS NOT NULL
        )
        OR
        (
            origin_type = 'DERIVED'
            AND resource_ref_id IS NULL
            AND message_id IS NULL
        )
    )
);

CREATE TABLE action_evidence (
    action_id    TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    PRIMARY KEY (action_id, evidence_id),
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE CASCADE,
    FOREIGN KEY (evidence_id) REFERENCES evidence(id) ON DELETE CASCADE
) WITHOUT ROWID;

CREATE TABLE approvals (
    id                         TEXT PRIMARY KEY,
    action_id                  TEXT NOT NULL,
    approval_no                INTEGER NOT NULL CHECK (approval_no >= 1),
    action_version             INTEGER NOT NULL CHECK (action_version >= 0),
    status                     TEXT NOT NULL CHECK (
        status IN ('ACTIVE', 'EXPIRED', 'CONSUMED', 'REVOKED')
    ),
    approved_by_account_id     TEXT NOT NULL,
    approved_by_display        TEXT CHECK (
        approved_by_display IS NULL
        OR length(approved_by_display) <= 200
    ),
    arguments_snapshot_json    TEXT NOT NULL CHECK (
        json_valid(arguments_snapshot_json)
        AND length(CAST(arguments_snapshot_json AS BLOB)) <= 65536
    ),
    canonical_arguments_hash   TEXT NOT NULL CHECK (length(canonical_arguments_hash) = 64),
    source_snapshot_json       TEXT NOT NULL CHECK (
        json_valid(source_snapshot_json)
        AND length(CAST(source_snapshot_json AS BLOB)) <= 65536
    ),
    source_snapshot_hash       TEXT NOT NULL CHECK (length(source_snapshot_hash) = 64),
    policy_version             TEXT NOT NULL,
    tool_schema_version        TEXT NOT NULL,
    idempotency_key            TEXT NOT NULL UNIQUE CHECK (length(idempotency_key) = 64),
    recovery_fingerprint       TEXT NOT NULL CHECK (length(recovery_fingerprint) = 64),
    approved_at_ms             INTEGER NOT NULL CHECK (approved_at_ms >= 0),
    expires_at_ms              INTEGER NOT NULL CHECK (expires_at_ms > approved_at_ms),
    consumed_at_ms             INTEGER CHECK (
        consumed_at_ms IS NULL OR consumed_at_ms >= approved_at_ms
    ),
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE CASCADE,
    FOREIGN KEY (approved_by_account_id)
        REFERENCES google_accounts(id) ON DELETE RESTRICT,
    UNIQUE (action_id, approval_no)
);

CREATE UNIQUE INDEX uq_approvals_one_active_per_action
    ON approvals(action_id)
    WHERE status = 'ACTIVE';

CREATE TABLE execution_attempts (
    id                      TEXT PRIMARY KEY,
    approval_id             TEXT NOT NULL,
    attempt_no              INTEGER NOT NULL CHECK (attempt_no >= 1),
    status                  TEXT NOT NULL CHECK (
        status IN (
            'CLAIMED', 'EXECUTING', 'UNKNOWN_RESULT',
            'SUCCEEDED', 'FAILED'
        )
    ),
    version                 INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    result_resource_ref_id  TEXT,
    response_metadata_json  TEXT CHECK (
        response_metadata_json IS NULL
        OR (
            json_valid(response_metadata_json)
            AND length(CAST(response_metadata_json AS BLOB)) <= 32768
        )
    ),
    error_code              TEXT,
    error_detail_json       TEXT CHECK (
        error_detail_json IS NULL
        OR (
            json_valid(error_detail_json)
            AND length(CAST(error_detail_json AS BLOB)) <= 32768
        )
    ),
    started_at_ms           INTEGER NOT NULL CHECK (started_at_ms >= 0),
    finished_at_ms          INTEGER CHECK (
        finished_at_ms IS NULL OR finished_at_ms >= started_at_ms
    ),
    FOREIGN KEY (approval_id) REFERENCES approvals(id) ON DELETE CASCADE,
    FOREIGN KEY (result_resource_ref_id)
        REFERENCES resource_refs(id) ON DELETE SET NULL,
    UNIQUE (approval_id, attempt_no)
);

CREATE UNIQUE INDEX uq_execution_attempts_one_active_per_approval
    ON execution_attempts(approval_id)
    WHERE status IN ('CLAIMED', 'EXECUTING', 'UNKNOWN_RESULT');

CREATE TABLE verifications (
    id                    TEXT PRIMARY KEY,
    execution_attempt_id  TEXT NOT NULL,
    verification_no       INTEGER NOT NULL CHECK (verification_no >= 1),
    status                TEXT NOT NULL CHECK (
        status IN ('VERIFIED', 'MISMATCH', 'NOT_FOUND', 'ERROR')
    ),
    normalizer_version    TEXT NOT NULL,
    expected_json         TEXT NOT NULL CHECK (
        json_valid(expected_json)
        AND length(CAST(expected_json AS BLOB)) <= 65536
    ),
    actual_json           TEXT CHECK (
        actual_json IS NULL
        OR (
            json_valid(actual_json)
            AND length(CAST(actual_json AS BLOB)) <= 65536
        )
    ),
    diff_json             TEXT NOT NULL CHECK (
        json_valid(diff_json)
        AND length(CAST(diff_json AS BLOB)) <= 65536
    ),
    verified_at_ms        INTEGER NOT NULL CHECK (verified_at_ms >= 0),
    FOREIGN KEY (execution_attempt_id)
        REFERENCES execution_attempts(id) ON DELETE CASCADE,
    UNIQUE (execution_attempt_id, verification_no)
);

CREATE TABLE trace_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    action_id       TEXT,
    event_type      TEXT NOT NULL,
    status          TEXT,
    duration_ms     INTEGER CHECK (
        duration_ms IS NULL OR duration_ms >= 0
    ),
    payload_json    TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(payload_json)
        AND length(CAST(payload_json AS BLOB)) <= 16384
    ),
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (action_id) REFERENCES actions(id) ON DELETE SET NULL
);

CREATE TABLE audit_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT,
    run_id          TEXT,
    action_id       TEXT,
    actor_type      TEXT NOT NULL CHECK (
        actor_type IN ('USER', 'SYSTEM', 'AGENT', 'MCP')
    ),
    actor_id        TEXT NOT NULL CHECK (length(actor_id) BETWEEN 1 AND 200),
    actor_display   TEXT CHECK (
        actor_display IS NULL OR length(actor_display) <= 200
    ),
    event_type      TEXT NOT NULL,
    outcome         TEXT NOT NULL,
    metadata_json   TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(metadata_json)
        AND length(CAST(metadata_json AS BLOB)) <= 16384
    ),
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0)
);

CREATE INDEX ix_conversations_account_updated
    ON conversations(account_id, updated_at_ms DESC, id DESC);

CREATE INDEX ix_messages_conversation_created
    ON messages(conversation_id, created_at_ms DESC, id DESC);

CREATE INDEX ix_messages_run_created
    ON messages(run_id, created_at_ms, id)
    WHERE run_id IS NOT NULL;

CREATE INDEX ix_runs_conversation_started
    ON runs(conversation_id, started_at_ms DESC, id DESC);

CREATE INDEX ix_runs_status_started
    ON runs(status, started_at_ms);

CREATE INDEX ix_plans_run_revision
    ON plans(run_id, revision_no DESC);

CREATE INDEX ix_actions_plan_status
    ON actions(plan_id, status, position);

CREATE INDEX ix_actions_recovery
    ON actions(status, updated_at_ms)
    WHERE status IN ('EXECUTING', 'UNKNOWN_RESULT', 'MISMATCH');

CREATE INDEX ix_action_dependencies_parent
    ON action_dependencies(depends_on_action_id, action_id);

CREATE INDEX ix_resource_refs_run_source
    ON resource_refs(run_id, source, captured_at_ms);

CREATE INDEX ix_evidence_run_created
    ON evidence(run_id, created_at_ms);

CREATE INDEX ix_evidence_resource_ref
    ON evidence(resource_ref_id)
    WHERE resource_ref_id IS NOT NULL;

CREATE INDEX ix_evidence_message
    ON evidence(message_id)
    WHERE message_id IS NOT NULL;

CREATE INDEX ix_action_evidence_evidence
    ON action_evidence(evidence_id, action_id);

CREATE INDEX ix_approvals_expiry
    ON approvals(status, expires_at_ms)
    WHERE status = 'ACTIVE';

CREATE INDEX ix_execution_attempts_recovery
    ON execution_attempts(status, started_at_ms)
    WHERE status IN ('EXECUTING', 'UNKNOWN_RESULT');

CREATE INDEX ix_trace_events_run_created
    ON trace_events(run_id, created_at_ms, id);

CREATE INDEX ix_audit_events_created
    ON audit_events(created_at_ms DESC, id DESC);

CREATE INDEX ix_audit_events_type_created
    ON audit_events(event_type, created_at_ms DESC, id DESC);

CREATE INDEX ix_audit_events_run_created
    ON audit_events(run_id, created_at_ms, id)
    WHERE run_id IS NOT NULL;

CREATE INDEX ix_audit_events_action_created
    ON audit_events(action_id, created_at_ms, id)
    WHERE action_id IS NOT NULL;

CREATE INDEX ix_audit_events_account_created
    ON audit_events(account_id, created_at_ms, id)
    WHERE account_id IS NOT NULL;
