-- Fresh-install current schema. Historical upgrade sources remain in Git history.
PRAGMA foreign_keys = ON;

BEGIN IMMEDIATE;

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
    ), terminal_result_kind TEXT
CHECK (
    terminal_result_kind IS NULL
    OR terminal_result_kind IN ('SUCCESS', 'PARTIAL', 'BLOCKED', 'FAILED', 'CANCELLED')
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
    created_at_ms   INTEGER NOT NULL CHECK (created_at_ms >= 0), review_status TEXT NOT NULL DEFAULT 'PASSED'
CHECK (review_status IN ('PASSED', 'REQUIRED', 'REVISE', 'RETRIEVE_MORE', 'BLOCKED')), review_version INTEGER NOT NULL DEFAULT 0
CHECK (review_version >= 0), review_disposition TEXT
CHECK (
    review_disposition IS NULL OR review_disposition IN (
        'PASS', 'REVISE', 'RETRIEVE_MORE', 'ROUTE_RECONSIDERATION', 'CONFIRM', 'BLOCK'
    )
),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, revision_no)
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

CREATE INDEX ix_action_dependencies_parent
    ON action_dependencies(depends_on_action_id, action_id);

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

CREATE TABLE "actions" (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 1),
    tool_name TEXT NOT NULL CHECK (length(tool_name) BETWEEN 1 AND 100),
    effect_type TEXT NOT NULL CHECK (effect_type IN ('READ', 'CREATE', 'UPDATE', 'SEND', 'DELETE')),
    approval_requirement TEXT NOT NULL CHECK (approval_requirement IN ('NONE', 'REQUIRED')),
    verification_policy TEXT NOT NULL CHECK (verification_policy IN ('NONE', 'GET_COMPARE', 'GET_ABSENT', 'SENT_LOOKUP')),
    recovery_policy TEXT NOT NULL CHECK (recovery_policy IN ('NONE', 'GET_TARGET', 'RESOURCE_SEARCH', 'MESSAGE_SEARCH')),
    target_resource_ref_id TEXT,
    status TEXT NOT NULL CHECK (status IN ('PROPOSED', 'MODIFIED', 'APPROVED', 'REJECTED', 'EXPIRED', 'EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED', 'FAILED', 'BLOCKED', 'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED')),
    arguments_json TEXT NOT NULL CHECK (json_valid(arguments_json) AND length(CAST(arguments_json AS BLOB)) <= 65536),
    arguments_hash TEXT NOT NULL CHECK (length(arguments_hash) = 64),
    expected_json TEXT NOT NULL CHECK (json_valid(expected_json) AND length(CAST(expected_json AS BLOB)) <= 65536),
    risk_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(risk_json) AND length(CAST(risk_json AS BLOB)) <= 16384),
    version INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    updated_at_ms INTEGER NOT NULL CHECK (updated_at_ms >= created_at_ms), connector_id TEXT NOT NULL DEFAULT 'google_workspace',
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    FOREIGN KEY (target_resource_ref_id) REFERENCES resource_refs(id) ON DELETE SET NULL,
    UNIQUE (plan_id, position),
    CHECK ((effect_type = 'READ' AND approval_requirement = 'NONE' AND verification_policy = 'NONE' AND recovery_policy = 'NONE') OR (effect_type = 'CREATE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_COMPARE' AND recovery_policy = 'RESOURCE_SEARCH') OR (effect_type = 'UPDATE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_COMPARE' AND recovery_policy = 'GET_TARGET') OR (effect_type = 'SEND' AND approval_requirement = 'REQUIRED' AND verification_policy = 'SENT_LOOKUP' AND recovery_policy = 'MESSAGE_SEARCH') OR (effect_type = 'DELETE' AND approval_requirement = 'REQUIRED' AND verification_policy = 'GET_ABSENT' AND recovery_policy = 'GET_TARGET'))
);

CREATE INDEX ix_actions_plan_status ON actions(plan_id, status, position);

CREATE INDEX ix_actions_recovery ON actions(status, updated_at_ms) WHERE status IN ('UNKNOWN_RESULT', 'MISMATCH', 'FAILED');

CREATE TRIGGER trg_runs_terminal_actions_guard_update
BEFORE UPDATE OF status ON runs
WHEN NEW.status IN ('COMPLETED', 'CANCELLED')
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN actions AS a ON a.plan_id = p.id
        WHERE p.run_id = NEW.id
          AND p.status <> 'SUPERSEDED'
          AND a.status NOT IN (
              'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
              'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
          )
    ) THEN RAISE(ABORT, 'NFR019_RUN_TERMINAL_ACTIONS') END;
END;

CREATE TRIGGER trg_plans_terminal_actions_guard_update
BEFORE UPDATE OF status ON plans
WHEN NEW.status IN ('COMPLETED', 'CANCELLED')
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1 FROM actions AS a
        WHERE a.plan_id = NEW.id
          AND a.status NOT IN (
              'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
              'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
          )
    ) THEN RAISE(ABORT, 'NFR019_PLAN_TERMINAL_ACTIONS') END;
END;

CREATE TRIGGER trg_actions_terminal_parent_guard_insert
BEFORE INSERT ON actions
WHEN NEW.status NOT IN (
    'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
    'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
)
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN runs AS r ON r.id = p.run_id
        WHERE p.id = NEW.plan_id
          AND (
              p.status IN ('COMPLETED', 'CANCELLED')
              OR (p.status <> 'SUPERSEDED' AND r.status IN ('COMPLETED', 'CANCELLED'))
          )
    ) THEN RAISE(ABORT, 'NFR019_TERMINAL_PARENT_ACTION') END;
END;

CREATE TRIGGER trg_actions_terminal_parent_guard_update
BEFORE UPDATE OF status, plan_id ON actions
WHEN NEW.status NOT IN (
    'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
    'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
)
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN runs AS r ON r.id = p.run_id
        WHERE p.id = NEW.plan_id
          AND (
              p.status IN ('COMPLETED', 'CANCELLED')
              OR (p.status <> 'SUPERSEDED' AND r.status IN ('COMPLETED', 'CANCELLED'))
          )
    ) THEN RAISE(ABORT, 'NFR019_TERMINAL_PARENT_ACTION') END;
END;

CREATE TRIGGER trg_actions_attempt_guard_update
BEFORE UPDATE OF status ON actions
WHEN NEW.effect_type <> 'READ'
  AND NEW.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'FAILED')
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        LEFT JOIN execution_attempts AS ea ON ea.approval_id = ap.id
        WHERE ap.action_id = NEW.id
          AND ap.status = 'CONSUMED'
          AND (
              (NEW.status = 'EXECUTING')
              OR (NEW.status = 'UNKNOWN_RESULT' AND ea.status = 'UNKNOWN_RESULT')
              OR (NEW.status = 'EXECUTED' AND ea.status = 'SUCCEEDED')
              OR (NEW.status = 'FAILED' AND ea.status = 'FAILED')
          )
    ) THEN RAISE(ABORT, 'NFR019_ACTION_ATTEMPT') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_evidence_insert
BEFORE INSERT ON action_evidence
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN evidence AS e ON e.id = NEW.evidence_id
        WHERE a.id = NEW.action_id
          AND e.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action evidence must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_evidence_update
BEFORE UPDATE OF action_id, evidence_id ON action_evidence
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN evidence AS e ON e.id = NEW.evidence_id
        WHERE a.id = NEW.action_id
          AND e.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action evidence must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_dependency_insert
BEFORE INSERT ON action_dependencies
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN actions AS d ON d.id = NEW.depends_on_action_id
        WHERE a.id = NEW.action_id
          AND a.plan_id = d.plan_id
    ) THEN RAISE(ABORT, 'action dependency must remain inside one plan') END;
END;

CREATE TRIGGER trg_plan_aggregate_dependency_update
BEFORE UPDATE OF action_id, depends_on_action_id ON action_dependencies
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN actions AS d ON d.id = NEW.depends_on_action_id
        WHERE a.id = NEW.action_id
          AND a.plan_id = d.plan_id
    ) THEN RAISE(ABORT, 'action dependency must remain inside one plan') END;
END;

CREATE TRIGGER trg_plan_aggregate_message_conversation_update
BEFORE UPDATE OF conversation_id ON messages
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM evidence AS e
        JOIN runs AS r ON r.id = e.run_id
        WHERE e.origin_type = 'USER_MESSAGE'
          AND e.message_id = OLD.id
          AND r.conversation_id <> NEW.conversation_id
    ) THEN RAISE(ABORT, 'message conversation update would break evidence links') END;
END;

CREATE TRIGGER trg_plan_aggregate_run_conversation_update
BEFORE UPDATE OF conversation_id ON runs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM evidence AS e
        JOIN messages AS m ON m.id = e.message_id
        WHERE e.origin_type = 'USER_MESSAGE'
          AND e.run_id = OLD.id
          AND m.conversation_id <> NEW.conversation_id
    ) THEN RAISE(ABORT, 'run conversation update would break evidence links') END;
END;

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

CREATE TABLE recovery_context_tombstones (
    run_id TEXT PRIMARY KEY REFERENCES runs(id),
    last_version INTEGER NOT NULL CHECK (last_version >= 0),
    cleared_at_ms INTEGER NOT NULL CHECK (cleared_at_ms >= 0)
);

CREATE UNIQUE INDEX ux_messages_terminal_assistant_per_run
ON messages(run_id)
WHERE role = 'ASSISTANT' AND run_id IS NOT NULL;

CREATE TABLE "verifications" (
    id                    TEXT PRIMARY KEY,
    execution_attempt_id  TEXT NOT NULL,
    verification_no       INTEGER NOT NULL CHECK (verification_no >= 1),
    status                TEXT NOT NULL CHECK (status IN ('VERIFIED', 'MISMATCH')),
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

CREATE TRIGGER trg_verifications_action_guard_insert
BEFORE INSERT ON verifications
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM execution_attempts AS ea
        JOIN approvals AS ap ON ap.id = ea.approval_id
        JOIN actions AS a ON a.id = ap.action_id
        WHERE ea.id = NEW.execution_attempt_id
          AND ea.status = 'SUCCEEDED'
          AND a.effect_type <> 'READ'
          AND a.status = 'EXECUTED'
    ) THEN RAISE(ABORT, 'NFR019_VERIFICATION_ACTION') END;
END;

CREATE TRIGGER trg_verifications_immutable_update
BEFORE UPDATE ON verifications
BEGIN
    SELECT RAISE(ABORT, 'NFR019_VERIFICATION_IMMUTABLE');
END;

CREATE TRIGGER trg_verifications_immutable_delete
BEFORE DELETE ON verifications
BEGIN
    SELECT RAISE(ABORT, 'NFR019_VERIFICATION_IMMUTABLE');
END;

CREATE TRIGGER trg_actions_verification_guard_update
BEFORE UPDATE OF status ON actions
WHEN NEW.effect_type <> 'READ' AND NEW.status IN ('VERIFIED', 'MISMATCH')
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN execution_attempts AS ea ON ea.approval_id = ap.id
        JOIN verifications AS v ON v.execution_attempt_id = ea.id
        WHERE ap.action_id = NEW.id AND v.status = NEW.status
    ) THEN RAISE(ABORT, 'NFR019_ACTION_VERIFICATION') END;
END;

CREATE TRIGGER trg_runs_active_approval_guard_update
BEFORE UPDATE OF status ON runs
WHEN NEW.status NOT IN (
    'WAITING_APPROVAL', 'VERIFYING', 'WAITING_CONFIRMATION',
    'REAUTH_REQUIRED', 'RECOVERY_REQUIRED', 'CANCEL_REQUESTED'
)
AND EXISTS (
    SELECT 1
    FROM plans AS p
    JOIN actions AS a ON a.plan_id = p.id
    JOIN approvals AS ap ON ap.action_id = a.id
    WHERE p.run_id = OLD.id AND ap.status = 'ACTIVE'
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_RUN_ACTIVE_APPROVAL');
END;

CREATE TABLE registered_connectors (
    connector_id TEXT PRIMARY KEY
        CHECK (length(connector_id) BETWEEN 1 AND 100)
);

CREATE TABLE registered_connector_resource_types (
    connector_id TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (length(resource_type) BETWEEN 1 AND 100),
    PRIMARY KEY (connector_id, resource_type),
    FOREIGN KEY (connector_id) REFERENCES registered_connectors(connector_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

CREATE UNIQUE INDEX uq_google_accounts_one_active
    ON google_accounts((1))
    WHERE disconnected_at_ms IS NULL;

CREATE TABLE "resource_refs" (
    id                  TEXT PRIMARY KEY,
    run_id              TEXT NOT NULL,
    connector_id        TEXT NOT NULL,
    resource_type       TEXT NOT NULL,
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
    FOREIGN KEY (connector_id, resource_type)
        REFERENCES registered_connector_resource_types(connector_id, resource_type)
        ON DELETE RESTRICT,
    UNIQUE (run_id, connector_id, resource_type, resource_id)
);

CREATE INDEX ix_resource_refs_run_time ON resource_refs(run_id, captured_at_ms);

CREATE INDEX ix_resource_refs_connector_identity
    ON resource_refs(run_id, connector_id, resource_type, resource_id);

CREATE TRIGGER trg_plan_aggregate_action_target_insert
BEFORE INSERT ON actions
WHEN NEW.target_resource_ref_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN resource_refs AS rr ON rr.id = NEW.target_resource_ref_id
        WHERE p.id = NEW.plan_id AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action target resource_ref must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_plan_update
BEFORE UPDATE OF plan_id, target_resource_ref_id ON actions
BEGIN
    SELECT CASE WHEN NEW.target_resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN resource_refs AS rr ON rr.id = NEW.target_resource_ref_id
        WHERE p.id = NEW.plan_id AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action target resource_ref must belong to plan run') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN evidence AS e ON e.id = ae.evidence_id
        JOIN plans AS p ON p.id = NEW.plan_id
        WHERE ae.action_id = OLD.id AND e.run_id <> p.run_id
    ) THEN RAISE(ABORT, 'action plan update would break evidence links') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS d ON d.id = ad.depends_on_action_id
        WHERE ad.action_id = OLD.id AND d.plan_id <> NEW.plan_id
    ) OR EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS dependent ON dependent.id = ad.action_id
        WHERE ad.depends_on_action_id = OLD.id AND dependent.plan_id <> NEW.plan_id
    ) THEN RAISE(ABORT, 'action plan update would break dependency links') END;
END;

CREATE TRIGGER trg_plan_aggregate_evidence_insert
BEFORE INSERT ON evidence
BEGIN
    SELECT CASE WHEN NEW.resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;
    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;
END;

CREATE TRIGGER trg_plan_aggregate_evidence_update
BEFORE UPDATE OF run_id, origin_type, resource_ref_id, message_id ON evidence
BEGIN
    SELECT CASE WHEN NEW.resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;
    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN actions AS a ON a.id = ae.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ae.evidence_id = OLD.id AND p.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'evidence run update would break action links') END;
END;

CREATE TRIGGER trg_plan_aggregate_plan_run_update
BEFORE UPDATE OF run_id ON plans
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN resource_refs AS rr ON rr.id = a.target_resource_ref_id
        WHERE a.plan_id = OLD.id AND rr.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN action_evidence AS ae ON ae.action_id = a.id
        JOIN evidence AS e ON e.id = ae.evidence_id
        WHERE a.plan_id = OLD.id AND e.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'plan run update would break aggregate links') END;
END;

CREATE TRIGGER trg_resource_refs_identity_immutable
BEFORE UPDATE OF run_id, connector_id, resource_type, resource_id ON resource_refs
WHEN NEW.run_id IS NOT OLD.run_id
  OR NEW.connector_id IS NOT OLD.connector_id
  OR NEW.resource_type IS NOT OLD.resource_type
  OR NEW.resource_id IS NOT OLD.resource_id
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_RESOURCE_REF_IDENTITY_IMMUTABLE');
END;

CREATE TRIGGER trg_plan_aggregate_resource_run_update
BEFORE UPDATE OF run_id ON resource_refs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        WHERE a.target_resource_ref_id = OLD.id AND p.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1 FROM evidence AS e
        WHERE e.resource_ref_id = OLD.id AND e.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM execution_attempts AS ea
        JOIN approvals AS ap ON ap.id = ea.approval_id
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ea.result_resource_ref_id = OLD.id AND p.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'resource_ref run update would break aggregate links') END;
END;

CREATE TRIGGER trg_actions_registered_connector_insert
BEFORE INSERT ON actions
WHEN NOT EXISTS (
    SELECT 1 FROM registered_connectors AS rc
    WHERE rc.connector_id = NEW.connector_id
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_ACTION_CONNECTOR_NOT_REGISTERED');
END;

CREATE TRIGGER trg_actions_registered_connector_update
BEFORE UPDATE OF connector_id ON actions
WHEN NOT EXISTS (
    SELECT 1 FROM registered_connectors AS rc
    WHERE rc.connector_id = NEW.connector_id
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_ACTION_CONNECTOR_NOT_REGISTERED');
END;

CREATE TRIGGER trg_plans_review_snapshot_insert
BEFORE INSERT ON plans
WHEN NEW.review_status NOT IN ('PASSED', 'REQUIRED')
OR (NEW.review_status = 'PASSED' AND NEW.review_disposition IS NOT 'PASS')
OR (
    NEW.review_status = 'REQUIRED'
    AND NEW.review_disposition IS NOT NULL
    AND NEW.review_disposition NOT IN (
        'REVISE', 'RETRIEVE_MORE', 'ROUTE_RECONSIDERATION', 'CONFIRM', 'BLOCK'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_PLAN_REVIEW_SNAPSHOT');
END;

CREATE TRIGGER trg_plans_review_snapshot_update
BEFORE UPDATE OF review_status, review_disposition ON plans
WHEN NEW.review_status NOT IN ('PASSED', 'REQUIRED')
OR (NEW.review_status = 'PASSED' AND NEW.review_disposition IS NOT 'PASS')
OR (
    NEW.review_status = 'REQUIRED'
    AND NEW.review_disposition IS NOT NULL
    AND NEW.review_disposition NOT IN (
        'REVISE', 'RETRIEVE_MORE', 'ROUTE_RECONSIDERATION', 'CONFIRM', 'BLOCK'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_PLAN_REVIEW_SNAPSHOT');
END;

CREATE TRIGGER trg_plans_lineage_immutable
BEFORE UPDATE OF run_id, revision_no ON plans
WHEN NEW.run_id IS NOT OLD.run_id OR NEW.revision_no IS NOT OLD.revision_no
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_PLAN_LINEAGE_IMMUTABLE');
END;

CREATE TRIGGER trg_plans_revision_insert_active_approval_guard
BEFORE INSERT ON plans
WHEN EXISTS (
    SELECT 1
    FROM plans AS prior_plan
    JOIN actions AS prior_action ON prior_action.plan_id = prior_plan.id
    JOIN approvals AS prior_approval ON prior_approval.action_id = prior_action.id
    WHERE prior_plan.run_id = NEW.run_id AND prior_approval.status = 'ACTIVE'
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_PLAN_ACTIVE_APPROVAL');
END;

CREATE TRIGGER trg_actions_plan_lineage_immutable
BEFORE UPDATE OF plan_id ON actions
WHEN NEW.plan_id IS NOT OLD.plan_id
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_ACTION_LINEAGE_IMMUTABLE');
END;

CREATE TRIGGER trg_approvals_lineage_immutable
BEFORE UPDATE OF action_id, action_version, approval_no ON approvals
WHEN NEW.action_id IS NOT OLD.action_id
  OR NEW.action_version IS NOT OLD.action_version
  OR NEW.approval_no IS NOT OLD.approval_no
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_APPROVAL_LINEAGE_IMMUTABLE');
END;

CREATE TRIGGER trg_attempts_lineage_immutable
BEFORE UPDATE OF approval_id, attempt_no ON execution_attempts
WHEN NEW.approval_id IS NOT OLD.approval_id OR NEW.attempt_no IS NOT OLD.attempt_no
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_ATTEMPT_LINEAGE_IMMUTABLE');
END;

CREATE TRIGGER trg_attempt_result_resource_guard_insert
BEFORE INSERT ON execution_attempts
WHEN NEW.result_resource_ref_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        JOIN resource_refs AS rr ON rr.id = NEW.result_resource_ref_id
        WHERE ap.id = NEW.approval_id AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'ISSUE128_ATTEMPT_RESULT_RESOURCE_RUN') END;
END;

CREATE TRIGGER trg_attempt_result_resource_guard_update
BEFORE UPDATE OF result_resource_ref_id ON execution_attempts
WHEN OLD.result_resource_ref_id IS NOT NULL OR NEW.result_resource_ref_id IS NOT NULL
BEGIN
    SELECT CASE WHEN NEW.result_resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        JOIN resource_refs AS rr ON rr.id = NEW.result_resource_ref_id
        WHERE ap.id = NEW.approval_id AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'ISSUE128_ATTEMPT_RESULT_RESOURCE_RUN') END;
    SELECT CASE WHEN OLD.result_resource_ref_id IS NOT NULL
        AND NEW.result_resource_ref_id IS NOT OLD.result_resource_ref_id
        THEN RAISE(ABORT, 'ISSUE128_ATTEMPT_RESULT_RESOURCE_IMMUTABLE') END;
END;

CREATE TRIGGER trg_approvals_active_action_guard_insert
BEFORE INSERT ON approvals
WHEN NEW.status = 'ACTIVE'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN runs AS r ON r.id = p.run_id
        WHERE a.id = NEW.action_id
          AND a.status = 'APPROVED'
          AND a.effect_type <> 'READ'
          AND a.version = NEW.action_version
          AND p.status = 'WAITING_APPROVAL'
          AND p.review_status = 'PASSED'
          AND p.review_disposition = 'PASS'
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
          AND NOT EXISTS (
              SELECT 1
              FROM execution_attempts AS prior_ea
              JOIN approvals AS prior_ap ON prior_ap.id = prior_ea.approval_id
              JOIN actions AS prior_a ON prior_a.id = prior_ap.action_id
              JOIN plans AS prior_p ON prior_p.id = prior_a.plan_id
              WHERE prior_p.run_id = p.run_id
                AND prior_ea.status = 'UNKNOWN_RESULT'
          )
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;

CREATE TRIGGER trg_approvals_active_action_guard_update
BEFORE UPDATE OF status, action_id, action_version ON approvals
WHEN NEW.status = 'ACTIVE'
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        JOIN runs AS r ON r.id = p.run_id
        WHERE a.id = NEW.action_id
          AND a.status = 'APPROVED'
          AND a.effect_type <> 'READ'
          AND a.version = NEW.action_version
          AND p.status = 'WAITING_APPROVAL'
          AND p.review_status = 'PASSED'
          AND p.review_disposition = 'PASS'
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
          AND NOT EXISTS (
              SELECT 1
              FROM execution_attempts AS prior_ea
              JOIN approvals AS prior_ap ON prior_ap.id = prior_ea.approval_id
              JOIN actions AS prior_a ON prior_a.id = prior_ap.action_id
              JOIN plans AS prior_p ON prior_p.id = prior_a.plan_id
              WHERE prior_p.run_id = p.run_id
                AND prior_ea.status = 'UNKNOWN_RESULT'
          )
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;

CREATE TRIGGER trg_actions_active_approval_guard_update
BEFORE UPDATE OF plan_id, connector_id, tool_name, effect_type, arguments_hash, status, version
ON actions
WHEN EXISTS (
    SELECT 1 FROM approvals AS ap
    WHERE ap.action_id = OLD.id AND ap.status = 'ACTIVE'
)
AND EXISTS (
    SELECT 1 FROM approvals AS ap
    WHERE ap.action_id = OLD.id AND ap.status = 'ACTIVE'
      AND (
          NEW.plan_id IS NOT OLD.plan_id
          OR NEW.connector_id IS NOT OLD.connector_id
          OR NEW.tool_name IS NOT OLD.tool_name
          OR NEW.effect_type IS NOT OLD.effect_type
          OR NEW.arguments_hash IS NOT ap.canonical_arguments_hash
          OR NEW.status <> 'APPROVED'
          OR NEW.version <> ap.action_version
      )
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_ACTION_ACTIVE_APPROVAL');
END;

CREATE TRIGGER trg_plans_inactive_approval_guard_update
BEFORE UPDATE OF status, run_id, revision_no, review_status, review_disposition ON plans
WHEN EXISTS (
    SELECT 1
    FROM actions AS a
    JOIN approvals AS ap ON ap.action_id = a.id
    WHERE a.plan_id = OLD.id AND ap.status = 'ACTIVE'
)
AND (
    NEW.status <> 'WAITING_APPROVAL'
    OR NEW.review_status <> 'PASSED'
    OR NEW.review_disposition <> 'PASS'
    OR NEW.run_id IS NOT OLD.run_id
    OR NEW.revision_no IS NOT OLD.revision_no
    OR NEW.revision_no <> (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=OLD.run_id)
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_PLAN_ACTIVE_APPROVAL');
END;

CREATE TRIGGER trg_actions_current_plan_authority_update
BEFORE UPDATE OF plan_id, status, version, arguments_json, arguments_hash ON actions
WHEN NOT EXISTS (
    SELECT 1
    FROM plans AS p
    WHERE p.id = OLD.plan_id
      AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
      AND p.status IN ('DRAFT', 'WAITING_APPROVAL', 'ACTIVE')
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_ACTION_NOT_CURRENT_PLAN_AUTHORITY');
END;

CREATE TRIGGER trg_actions_unknown_result_guard_update
BEFORE UPDATE OF status ON actions
WHEN NEW.status IN ('APPROVED', 'EXECUTING')
AND EXISTS (
    SELECT 1
    FROM plans AS owner_plan
    JOIN plans AS other_plan ON other_plan.run_id = owner_plan.run_id
    JOIN actions AS other_action ON other_action.plan_id = other_plan.id
    JOIN approvals AS other_approval ON other_approval.action_id = other_action.id
    JOIN execution_attempts AS other_attempt ON other_attempt.approval_id = other_approval.id
    WHERE owner_plan.id = OLD.plan_id AND other_attempt.status = 'UNKNOWN_RESULT'
)
BEGIN
    SELECT RAISE(ABORT, 'ISSUE128_UNKNOWN_RESULT_AUTHORITY');
END;

CREATE TRIGGER trg_attempts_action_guard_insert
BEFORE INSERT ON execution_attempts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        JOIN runs AS r ON r.id = p.run_id
        WHERE ap.id = NEW.approval_id
          AND ap.status = 'CONSUMED'
          AND p.status = 'WAITING_APPROVAL'
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
          AND (
              (NEW.status IN ('CLAIMED', 'EXECUTING') AND a.status = 'EXECUTING')
              OR (NEW.status = 'UNKNOWN_RESULT' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT'))
              OR (NEW.status = 'SUCCEEDED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED', 'MISMATCH'))
              OR (NEW.status = 'FAILED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'FAILED'))
          )
          AND NOT EXISTS (
              SELECT 1
              FROM execution_attempts AS prior_ea
              JOIN approvals AS prior_ap ON prior_ap.id = prior_ea.approval_id
              JOIN actions AS prior_a ON prior_a.id = prior_ap.action_id
              JOIN plans AS prior_p ON prior_p.id = prior_a.plan_id
              WHERE prior_p.run_id = p.run_id AND prior_ea.status = 'UNKNOWN_RESULT'
          )
    ) THEN RAISE(ABORT, 'NFR019_ATTEMPT_ACTION') END;
END;

CREATE TRIGGER trg_attempts_action_guard_update
BEFORE UPDATE OF status, approval_id ON execution_attempts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN actions AS a ON a.id = ap.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ap.id = NEW.approval_id
          AND ap.status = 'CONSUMED'
          AND p.status IN ('WAITING_APPROVAL', 'ACTIVE')
          AND p.revision_no = (SELECT MAX(p2.revision_no) FROM plans AS p2 WHERE p2.run_id=p.run_id)
          AND (
              (NEW.status IN ('CLAIMED', 'EXECUTING') AND a.status = 'EXECUTING')
              OR (NEW.status = 'UNKNOWN_RESULT' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT'))
              OR (NEW.status = 'SUCCEEDED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED', 'MISMATCH'))
              OR (NEW.status = 'FAILED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'FAILED'))
          )
    ) THEN RAISE(ABORT, 'NFR019_ATTEMPT_ACTION') END;
END;

CREATE TRIGGER recovery_context_reason_matrix_insert
BEFORE INSERT ON recovery_contexts
FOR EACH ROW
WHEN NOT (
    NEW.recovery_fingerprint <> ''
    AND ((NEW.reason = 'UNKNOWN_RESULT'
        AND NEW.scope = 'ACTION'
        AND NEW.action_id IS NOT NULL
        AND NEW.execution_attempt_id IS NOT NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NULL)
    OR
    (NEW.reason = 'VERIFICATION_MISMATCH'
        AND NEW.scope = 'ACTION'
        AND NEW.action_id IS NOT NULL
        AND NEW.execution_attempt_id IS NOT NULL
        AND NEW.verification_id IS NOT NULL
        AND NEW.observed_external_state_fingerprint IS NOT NULL
        AND NEW.verification_input_fingerprint IS NOT NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NULL)
    OR
    (NEW.reason = 'CHECKPOINT_MISMATCH'
        AND NEW.scope = 'RUN'
        AND NEW.action_id IS NULL
        AND NEW.execution_attempt_id IS NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.registered_resume_target_json IS NOT NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NOT NULL)
    OR
    (NEW.reason = 'CONTRACT_VIOLATION'
        AND NEW.scope = 'RUN'
        AND NEW.action_id IS NULL
        AND NEW.execution_attempt_id IS NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NOT NULL))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid RecoveryContext reason/scope/reference matrix');
END;

CREATE TRIGGER recovery_context_reason_matrix_update
BEFORE UPDATE ON recovery_contexts
FOR EACH ROW
WHEN NOT (
    NEW.recovery_fingerprint <> ''
    AND ((NEW.reason = 'UNKNOWN_RESULT'
        AND NEW.scope = 'ACTION'
        AND NEW.action_id IS NOT NULL
        AND NEW.execution_attempt_id IS NOT NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NULL)
    OR
    (NEW.reason = 'VERIFICATION_MISMATCH'
        AND NEW.scope = 'ACTION'
        AND NEW.action_id IS NOT NULL
        AND NEW.execution_attempt_id IS NOT NULL
        AND NEW.verification_id IS NOT NULL
        AND NEW.observed_external_state_fingerprint IS NOT NULL
        AND NEW.verification_input_fingerprint IS NOT NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NULL)
    OR
    (NEW.reason = 'CHECKPOINT_MISMATCH'
        AND NEW.scope = 'RUN'
        AND NEW.action_id IS NULL
        AND NEW.execution_attempt_id IS NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.registered_resume_target_json IS NOT NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NOT NULL)
    OR
    (NEW.reason = 'CONTRACT_VIOLATION'
        AND NEW.scope = 'RUN'
        AND NEW.action_id IS NULL
        AND NEW.execution_attempt_id IS NULL
        AND NEW.verification_id IS NULL
        AND NEW.observed_external_state_fingerprint IS NULL
        AND NEW.verification_input_fingerprint IS NULL
        AND NEW.contract_or_checkpoint_fingerprint IS NOT NULL))
)
BEGIN
    SELECT RAISE(ABORT, 'invalid RecoveryContext reason/scope/reference matrix');
END;

CREATE TABLE workflow_bindings (
    workflow_key TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    langgraph_thread_id TEXT NOT NULL UNIQUE,
    graph_profile TEXT NOT NULL,
    graph_version TEXT NOT NULL,
    requested_mode TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

INSERT INTO registered_connectors (connector_id) VALUES ('google_workspace');

INSERT INTO registered_connector_resource_types (connector_id, resource_type) VALUES
    ('google_workspace', 'calendar'),
    ('google_workspace', 'calendar_event'),
    ('google_workspace', 'calendar_freebusy'),
    ('google_workspace', 'gmail_attachment'),
    ('google_workspace', 'gmail_draft'),
    ('google_workspace', 'gmail_message'),
    ('google_workspace', 'gmail_thread'),
    ('google_workspace', 'task'),
    ('google_workspace', 'task_list');

COMMIT;

PRAGMA foreign_key_check;
