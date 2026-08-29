-- Migration 0016: close durable provenance, current-parent, registry, and account invariants.
-- SQLite / UTF-8

PRAGMA foreign_keys = OFF;

BEGIN IMMEDIATE;

CREATE TABLE issue128_invariant_preflight (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

-- Normalize the split Review gate/disposition introduced by 0004/0010. The
-- older review_status values are historical projections of the exact current
-- disposition, while PASSED before 0010 deterministically meant PASS.
UPDATE plans
SET review_disposition = CASE
        WHEN review_disposition IS NOT NULL THEN review_disposition
        WHEN review_status = 'PASSED' THEN 'PASS'
        WHEN review_status = 'REVISE' THEN 'REVISE'
        WHEN review_status = 'RETRIEVE_MORE' THEN 'RETRIEVE_MORE'
        WHEN review_status = 'BLOCKED' THEN 'BLOCK'
        ELSE NULL
    END,
    review_status = CASE
        WHEN review_disposition = 'PASS' OR (
            review_disposition IS NULL AND review_status = 'PASSED'
        ) THEN 'PASSED'
        ELSE 'REQUIRED'
    END;

INSERT INTO issue128_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM plans
    WHERE NOT (
        (review_status = 'PASSED' AND review_disposition = 'PASS')
        OR (
            review_status = 'REQUIRED'
            AND (review_disposition IS NULL OR review_disposition <> 'PASS')
        )
    )
);

CREATE TABLE registered_connectors (
    connector_id TEXT PRIMARY KEY
        CHECK (length(connector_id) BETWEEN 1 AND 100)
);

INSERT INTO registered_connectors (connector_id) VALUES ('google_workspace');

CREATE TABLE registered_connector_resource_types (
    connector_id TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (length(resource_type) BETWEEN 1 AND 100),
    PRIMARY KEY (connector_id, resource_type),
    FOREIGN KEY (connector_id) REFERENCES registered_connectors(connector_id)
        ON DELETE RESTRICT
) WITHOUT ROWID;

INSERT INTO registered_connector_resource_types (connector_id, resource_type) VALUES
    ('google_workspace', 'gmail_thread'),
    ('google_workspace', 'gmail_message'),
    ('google_workspace', 'gmail_attachment'),
    ('google_workspace', 'gmail_draft'),
    ('google_workspace', 'task_list'),
    ('google_workspace', 'task'),
    ('google_workspace', 'calendar'),
    ('google_workspace', 'calendar_event'),
    ('google_workspace', 'calendar_freebusy');

INSERT INTO issue128_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1 FROM actions AS a
    WHERE NOT EXISTS (
        SELECT 1 FROM registered_connectors AS rc
        WHERE rc.connector_id = a.connector_id
    )
);

INSERT INTO issue128_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM resource_refs AS rr
    WHERE CASE
        WHEN rr.resource_type IN (
            'gmail_thread', 'gmail_message', 'gmail_attachment', 'gmail_draft',
            'task_list', 'task', 'calendar', 'calendar_event', 'calendar_freebusy'
        ) THEN rr.resource_type
        WHEN rr.source = 'GMAIL' AND rr.resource_type IN ('THREAD', 'GMAIL_THREAD')
            THEN 'gmail_thread'
        WHEN rr.source = 'GMAIL' AND rr.resource_type IN ('MESSAGE', 'GMAIL_MESSAGE')
            THEN 'gmail_message'
        WHEN rr.source = 'GMAIL' AND rr.resource_type = 'GMAIL_ATTACHMENT'
            THEN 'gmail_attachment'
        WHEN rr.source = 'GMAIL' AND rr.resource_type = 'GMAIL_DRAFT'
            THEN 'gmail_draft'
        WHEN rr.source = 'TASKS' AND rr.resource_type = 'TASK_LIST'
            THEN 'task_list'
        WHEN rr.source = 'TASKS' AND rr.resource_type = 'TASK'
            THEN 'task'
        WHEN rr.source = 'CALENDAR' AND rr.resource_type = 'CALENDAR'
            THEN 'calendar'
        WHEN rr.source = 'CALENDAR' AND rr.resource_type IN ('EVENT', 'CALENDAR_EVENT')
            THEN 'calendar_event'
        WHEN rr.source = 'CALENDAR' AND rr.resource_type = 'CALENDAR_FREEBUSY'
            THEN 'calendar_freebusy'
        ELSE NULL
    END IS NULL
);

-- Keep exactly one current connected account before installing the DB-level
-- single-active constraint. Historical rows and conversation ownership remain.
UPDATE google_accounts
SET disconnected_at_ms = MAX(
        connected_at_ms,
        COALESCE(
            (
                SELECT winner.connected_at_ms
                FROM google_accounts AS winner
                WHERE winner.disconnected_at_ms IS NULL
                ORDER BY winner.connected_at_ms DESC, winner.id DESC
                LIMIT 1
            ),
            connected_at_ms
        )
    )
WHERE disconnected_at_ms IS NULL
  AND id <> COALESCE(
      (
          SELECT winner.id
          FROM google_accounts AS winner
          WHERE winner.disconnected_at_ms IS NULL
          ORDER BY winner.connected_at_ms DESC, winner.id DESC
          LIMIT 1
      ),
      id
  );

CREATE UNIQUE INDEX uq_google_accounts_one_active
    ON google_accounts((1))
    WHERE disconnected_at_ms IS NULL;

DROP TRIGGER IF EXISTS trg_plan_aggregate_action_target_insert;
DROP TRIGGER IF EXISTS trg_plan_aggregate_action_plan_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_evidence_insert;
DROP TRIGGER IF EXISTS trg_plan_aggregate_evidence_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_plan_run_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_resource_run_update;

CREATE TABLE resource_refs__canonical_identity (
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

INSERT INTO resource_refs__canonical_identity (
    id, run_id, connector_id, resource_type, resource_id,
    parent_resource_id, canonical_url, title, event_time_ms,
    version_token, metadata_json, captured_at_ms
)
SELECT
    id,
    run_id,
    connector_id,
    CASE
        WHEN resource_type IN (
            'gmail_thread', 'gmail_message', 'gmail_attachment', 'gmail_draft',
            'task_list', 'task', 'calendar', 'calendar_event', 'calendar_freebusy'
        ) THEN resource_type
        WHEN source = 'GMAIL' AND resource_type IN ('THREAD', 'GMAIL_THREAD')
            THEN 'gmail_thread'
        WHEN source = 'GMAIL' AND resource_type IN ('MESSAGE', 'GMAIL_MESSAGE')
            THEN 'gmail_message'
        WHEN source = 'GMAIL' AND resource_type = 'GMAIL_ATTACHMENT'
            THEN 'gmail_attachment'
        WHEN source = 'GMAIL' AND resource_type = 'GMAIL_DRAFT'
            THEN 'gmail_draft'
        WHEN source = 'TASKS' AND resource_type = 'TASK_LIST' THEN 'task_list'
        WHEN source = 'TASKS' AND resource_type = 'TASK' THEN 'task'
        WHEN source = 'CALENDAR' AND resource_type = 'CALENDAR' THEN 'calendar'
        WHEN source = 'CALENDAR' AND resource_type IN ('EVENT', 'CALENDAR_EVENT')
            THEN 'calendar_event'
        WHEN source = 'CALENDAR' AND resource_type = 'CALENDAR_FREEBUSY'
            THEN 'calendar_freebusy'
    END,
    resource_id,
    parent_resource_id,
    canonical_url,
    title,
    event_time_ms,
    version_token,
    metadata_json,
    captured_at_ms
FROM resource_refs;

DROP TABLE resource_refs;
ALTER TABLE resource_refs__canonical_identity RENAME TO resource_refs;

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

DROP TRIGGER IF EXISTS trg_approvals_active_action_guard_insert;
DROP TRIGGER IF EXISTS trg_approvals_active_action_guard_update;
DROP TRIGGER IF EXISTS trg_actions_active_approval_guard_update;
DROP TRIGGER IF EXISTS trg_plans_inactive_approval_guard_update;
DROP TRIGGER IF EXISTS trg_attempts_action_guard_insert;
DROP TRIGGER IF EXISTS trg_attempts_action_guard_update;

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

DROP TABLE issue128_invariant_preflight;

COMMIT;

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
