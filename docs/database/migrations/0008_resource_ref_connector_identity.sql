-- Migration 0008: make connector-aware ResourceRef identity the single authority.
-- SQLite / UTF-8
--
-- 0007 introduced connector_id but retained the pre-connector UNIQUE key as a
-- compatibility constraint.  Rebuild the table so different connectors can
-- persist the same external id (even when they share the same source vocabulary).

PRAGMA foreign_keys = OFF;
BEGIN IMMEDIATE;

DROP TRIGGER IF EXISTS trg_plan_aggregate_action_target_insert;
DROP TRIGGER IF EXISTS trg_plan_aggregate_action_plan_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_evidence_insert;
DROP TRIGGER IF EXISTS trg_plan_aggregate_evidence_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_plan_run_update;
DROP TRIGGER IF EXISTS trg_plan_aggregate_resource_run_update;

CREATE TABLE resource_refs__connector_identity (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    connector_id TEXT NOT NULL CHECK (length(connector_id) BETWEEN 1 AND 100),
    source TEXT NOT NULL,
    resource_type TEXT NOT NULL CHECK (
        resource_type IN ('THREAD', 'MESSAGE', 'TASK', 'EVENT', 'TASK_LIST', 'CALENDAR')
    ),
    resource_id TEXT NOT NULL,
    parent_resource_id TEXT,
    canonical_url TEXT,
    title TEXT,
    event_time_ms INTEGER,
    version_token TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (
        json_valid(metadata_json)
        AND length(CAST(metadata_json AS BLOB)) <= 32768
    ),
    captured_at_ms INTEGER NOT NULL CHECK (captured_at_ms >= 0),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    UNIQUE (run_id, connector_id, resource_type, resource_id)
);

INSERT INTO resource_refs__connector_identity (
    id, run_id, connector_id, source, resource_type, resource_id,
    parent_resource_id, canonical_url, title, event_time_ms,
    version_token, metadata_json, captured_at_ms
)
SELECT
    id, run_id, connector_id, source, resource_type, resource_id,
    parent_resource_id, canonical_url, title, event_time_ms,
    version_token, metadata_json, captured_at_ms
FROM resource_refs;

DROP TABLE resource_refs;
ALTER TABLE resource_refs__connector_identity RENAME TO resource_refs;

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
        WHERE p.id = NEW.plan_id
          AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action target resource_ref must belong to plan run') END;
END;

CREATE TRIGGER trg_plan_aggregate_action_plan_update
BEFORE UPDATE OF plan_id, target_resource_ref_id ON actions
BEGIN
    SELECT CASE WHEN NEW.target_resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM plans AS p
        JOIN resource_refs AS rr ON rr.id = NEW.target_resource_ref_id
        WHERE p.id = NEW.plan_id
          AND rr.run_id = p.run_id
    ) THEN RAISE(ABORT, 'action target resource_ref must belong to plan run') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN evidence AS e ON e.id = ae.evidence_id
        JOIN plans AS p ON p.id = NEW.plan_id
        WHERE ae.action_id = OLD.id
          AND e.run_id <> p.run_id
    ) THEN RAISE(ABORT, 'action plan update would break evidence links') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS d ON d.id = ad.depends_on_action_id
        WHERE ad.action_id = OLD.id
          AND d.plan_id <> NEW.plan_id
    ) OR EXISTS (
        SELECT 1
        FROM action_dependencies AS ad
        JOIN actions AS dependent ON dependent.id = ad.action_id
        WHERE ad.depends_on_action_id = OLD.id
          AND dependent.plan_id <> NEW.plan_id
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

CREATE TRIGGER trg_plan_aggregate_resource_run_update
BEFORE UPDATE OF run_id ON resource_refs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        WHERE a.target_resource_ref_id = OLD.id AND p.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM evidence AS e
        WHERE e.resource_ref_id = OLD.id AND e.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'resource_ref run update would break aggregate links') END;
END;

COMMIT;
PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
