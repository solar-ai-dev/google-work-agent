-- Migration 0005: NFR-019 cross-aggregate integrity enforcement.
-- SQLite / UTF-8

-- Fail closed when an existing database already contains an impossible snapshot.
CREATE TABLE nfr019_invariant_preflight (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

INSERT INTO nfr019_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM approvals AS ap
    JOIN actions AS a ON a.id = ap.action_id
    JOIN plans AS p ON p.id = a.plan_id
    JOIN runs AS r ON r.id = p.run_id
    WHERE ap.status = 'ACTIVE'
      AND (
          a.status <> 'APPROVED'
          OR a.effect_type = 'READ'
          OR ap.action_version <> a.version
          OR p.status NOT IN ('WAITING_APPROVAL', 'ACTIVE')
          OR r.status IN ('COMPLETED', 'CANCELLED', 'FAILED', 'BLOCKED')
      )
);

INSERT INTO nfr019_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM runs AS r
    JOIN plans AS p ON p.run_id = r.id
    JOIN actions AS a ON a.plan_id = p.id
    WHERE p.status <> 'SUPERSEDED'
      AND (
          (r.status = 'COMPLETED' AND a.status NOT IN (
              'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
              'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
          ))
          OR
          (r.status = 'CANCELLED' AND a.status NOT IN (
              'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
              'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
          ))
      )
);

INSERT INTO nfr019_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM plans AS p
    JOIN actions AS a ON a.plan_id = p.id
    WHERE p.status IN ('COMPLETED', 'CANCELLED')
      AND a.status NOT IN (
          'REJECTED', 'VERIFIED', 'FAILED', 'BLOCKED',
          'DEPENDENCY_BLOCKED', 'MISMATCH', 'CANCELLED'
      )
);

INSERT INTO nfr019_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM execution_attempts AS ea
    JOIN approvals AS ap ON ap.id = ea.approval_id
    JOIN actions AS a ON a.id = ap.action_id
    WHERE ap.status <> 'CONSUMED'
       OR (ea.status IN ('CLAIMED', 'EXECUTING') AND a.status <> 'EXECUTING')
       OR (ea.status = 'UNKNOWN_RESULT' AND a.status <> 'UNKNOWN_RESULT')
       OR (ea.status = 'SUCCEEDED' AND a.status NOT IN ('EXECUTED', 'VERIFIED', 'MISMATCH'))
       OR (ea.status = 'FAILED' AND a.status <> 'FAILED')
);

INSERT INTO nfr019_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1
    FROM actions AS a
    WHERE a.effect_type <> 'READ'
      AND (
          (a.status = 'UNKNOWN_RESULT' AND NOT EXISTS (
              SELECT 1
              FROM approvals AS ap
              JOIN execution_attempts AS ea ON ea.approval_id = ap.id
              WHERE ap.action_id = a.id AND ea.status = 'UNKNOWN_RESULT'
          ))
          OR
          (a.status = 'EXECUTED' AND NOT EXISTS (
              SELECT 1
              FROM approvals AS ap
              JOIN execution_attempts AS ea ON ea.approval_id = ap.id
              WHERE ap.action_id = a.id AND ea.status = 'SUCCEEDED'
          ))
          OR
          (a.status = 'FAILED' AND NOT EXISTS (
              SELECT 1
              FROM approvals AS ap
              JOIN execution_attempts AS ea ON ea.approval_id = ap.id
              WHERE ap.action_id = a.id AND ea.status = 'FAILED'
          ))
          OR
          (a.status IN ('VERIFIED', 'MISMATCH') AND NOT EXISTS (
              SELECT 1
              FROM approvals AS ap
              JOIN execution_attempts AS ea ON ea.approval_id = ap.id
              JOIN verifications AS v ON v.execution_attempt_id = ea.id
              WHERE ap.action_id = a.id AND v.status = a.status
          ))
      )
);

DROP TABLE nfr019_invariant_preflight;

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
          AND p.status IN ('WAITING_APPROVAL', 'ACTIVE')
          AND r.status NOT IN ('COMPLETED', 'CANCELLED', 'FAILED', 'BLOCKED')
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
          AND p.status IN ('WAITING_APPROVAL', 'ACTIVE')
          AND r.status NOT IN ('COMPLETED', 'CANCELLED', 'FAILED', 'BLOCKED')
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;

CREATE TRIGGER trg_actions_active_approval_guard_update
BEFORE UPDATE OF status, version ON actions
WHEN EXISTS (
    SELECT 1 FROM approvals AS ap
    WHERE ap.action_id = OLD.id AND ap.status = 'ACTIVE'
)
AND (NEW.status <> 'APPROVED' OR NEW.version <> OLD.version)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_ACTION_ACTIVE_APPROVAL');
END;

CREATE TRIGGER trg_runs_active_approval_guard_update
BEFORE UPDATE OF status ON runs
WHEN NEW.status IN ('COMPLETED', 'CANCELLED', 'FAILED', 'BLOCKED')
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

CREATE TRIGGER trg_plans_inactive_approval_guard_update
BEFORE UPDATE OF status ON plans
WHEN NEW.status NOT IN ('WAITING_APPROVAL', 'ACTIVE')
AND EXISTS (
    SELECT 1
    FROM actions AS a
    JOIN approvals AS ap ON ap.action_id = a.id
    WHERE a.plan_id = OLD.id AND ap.status = 'ACTIVE'
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_PLAN_ACTIVE_APPROVAL');
END;

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

CREATE TRIGGER trg_attempts_action_guard_insert
BEFORE INSERT ON execution_attempts
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1
        FROM approvals AS ap
        JOIN actions AS a ON a.id = ap.action_id
        WHERE ap.id = NEW.approval_id
          AND ap.status = 'CONSUMED'
          AND (
              (NEW.status IN ('CLAIMED', 'EXECUTING') AND a.status = 'EXECUTING')
              OR (NEW.status = 'UNKNOWN_RESULT' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT'))
              OR (NEW.status = 'SUCCEEDED' AND a.status IN (
                  'EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED', 'MISMATCH'
              ))
              OR (NEW.status = 'FAILED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'FAILED'))
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
        WHERE ap.id = NEW.approval_id
          AND ap.status = 'CONSUMED'
          AND (
              (NEW.status IN ('CLAIMED', 'EXECUTING') AND a.status = 'EXECUTING')
              OR (NEW.status = 'UNKNOWN_RESULT' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT'))
              OR (NEW.status = 'SUCCEEDED' AND a.status IN (
                  'EXECUTING', 'UNKNOWN_RESULT', 'EXECUTED', 'VERIFIED', 'MISMATCH'
              ))
              OR (NEW.status = 'FAILED' AND a.status IN ('EXECUTING', 'UNKNOWN_RESULT', 'FAILED'))
          )
    ) THEN RAISE(ABORT, 'NFR019_ATTEMPT_ACTION') END;
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
