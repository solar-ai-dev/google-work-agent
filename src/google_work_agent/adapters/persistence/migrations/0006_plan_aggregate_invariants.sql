-- Migration 0006: Plan Aggregate cross-run/conversation/plan invariants.
-- SQLite / UTF-8

-- Existing populated databases must fail closed instead of installing guards
-- over an already-impossible snapshot.
CREATE TABLE plan_aggregate_invariant_preflight (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

-- Action target ResourceRef must belong to the Action Plan's Run.
INSERT INTO plan_aggregate_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM actions AS a
    JOIN plans AS p ON p.id = a.plan_id
    JOIN resource_refs AS rr ON rr.id = a.target_resource_ref_id
    WHERE rr.run_id <> p.run_id
);

-- Resource-backed Evidence must reference a ResourceRef from the same Run.
INSERT INTO plan_aggregate_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM evidence AS e
    JOIN resource_refs AS rr ON rr.id = e.resource_ref_id
    WHERE rr.run_id <> e.run_id
);

-- USER_MESSAGE Evidence may come from an older Run, but only from the same Conversation.
INSERT INTO plan_aggregate_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM evidence AS e
    JOIN runs AS r ON r.id = e.run_id
    JOIN messages AS m ON m.id = e.message_id
    WHERE e.origin_type = 'USER_MESSAGE'
      AND m.conversation_id <> r.conversation_id
);

-- Every ActionEvidence edge must stay inside the Plan Run.
INSERT INTO plan_aggregate_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM action_evidence AS ae
    JOIN actions AS a ON a.id = ae.action_id
    JOIN plans AS p ON p.id = a.plan_id
    JOIN evidence AS e ON e.id = ae.evidence_id
    WHERE e.run_id <> p.run_id
);

-- Dependencies are intra-plan only.
INSERT INTO plan_aggregate_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM action_dependencies AS ad
    JOIN actions AS a ON a.id = ad.action_id
    JOIN actions AS d ON d.id = ad.depends_on_action_id
    WHERE a.plan_id <> d.plan_id
);

DROP TABLE plan_aggregate_invariant_preflight;

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
        SELECT 1
        FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id
          AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;

    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id
          AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;
END;

CREATE TRIGGER trg_plan_aggregate_evidence_update
BEFORE UPDATE OF run_id, origin_type, resource_ref_id, message_id ON evidence
BEGIN
    SELECT CASE WHEN NEW.resource_ref_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM resource_refs AS rr
        WHERE rr.id = NEW.resource_ref_id
          AND rr.run_id = NEW.run_id
    ) THEN RAISE(ABORT, 'evidence resource_ref must belong to evidence run') END;

    SELECT CASE WHEN NEW.origin_type = 'USER_MESSAGE' AND NOT EXISTS (
        SELECT 1
        FROM runs AS r
        JOIN messages AS m ON m.id = NEW.message_id
        WHERE r.id = NEW.run_id
          AND m.conversation_id = r.conversation_id
    ) THEN RAISE(ABORT, 'user-message evidence must belong to run conversation') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM action_evidence AS ae
        JOIN actions AS a ON a.id = ae.action_id
        JOIN plans AS p ON p.id = a.plan_id
        WHERE ae.evidence_id = OLD.id
          AND p.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'evidence run update would break action links') END;
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

-- Protect reverse mutation directions for otherwise-valid existing links.
CREATE TRIGGER trg_plan_aggregate_plan_run_update
BEFORE UPDATE OF run_id ON plans
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN resource_refs AS rr ON rr.id = a.target_resource_ref_id
        WHERE a.plan_id = OLD.id
          AND rr.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN action_evidence AS ae ON ae.action_id = a.id
        JOIN evidence AS e ON e.id = ae.evidence_id
        WHERE a.plan_id = OLD.id
          AND e.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'plan run update would break aggregate links') END;
END;

CREATE TRIGGER trg_plan_aggregate_resource_run_update
BEFORE UPDATE OF run_id ON resource_refs
BEGIN
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM actions AS a
        JOIN plans AS p ON p.id = a.plan_id
        WHERE a.target_resource_ref_id = OLD.id
          AND p.run_id <> NEW.run_id
    ) OR EXISTS (
        SELECT 1
        FROM evidence AS e
        WHERE e.resource_ref_id = OLD.id
          AND e.run_id <> NEW.run_id
    ) THEN RAISE(ABORT, 'resource_ref run update would break aggregate links') END;
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
