-- Migration 0015: canonical Verification and current Write Plan final defense.
-- SQLite / UTF-8

PRAGMA foreign_keys = OFF;

BEGIN IMMEDIATE;

-- Canonical provides no deterministic conversion for technical observations
-- persisted as Verification lifecycle states. Fail closed instead of coercing.
CREATE TABLE issue127_invariant_preflight (
    valid INTEGER NOT NULL CHECK (valid = 1)
);

INSERT INTO issue127_invariant_preflight (valid)
SELECT 0
WHERE EXISTS (
    SELECT 1 FROM verifications
    WHERE status NOT IN ('VERIFIED', 'MISMATCH')
);

-- An existing ACTIVE Approval may survive a nonterminal Run suspension, but its
-- Action and current published Write Plan authority must remain exact.
INSERT INTO issue127_invariant_preflight (valid)
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
          OR p.status <> 'WAITING_APPROVAL'
          OR r.status NOT IN (
              'WAITING_APPROVAL', 'VERIFYING', 'WAITING_CONFIRMATION',
              'REAUTH_REQUIRED', 'RECOVERY_REQUIRED', 'CANCEL_REQUESTED'
          )
      )
);

DROP TABLE issue127_invariant_preflight;

DROP TRIGGER trg_actions_verification_guard_update;
DROP TRIGGER trg_verifications_action_guard_insert;
DROP TRIGGER trg_verifications_immutable_update;
DROP TRIGGER trg_verifications_immutable_delete;

CREATE TABLE verifications__canonical_final (
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

INSERT INTO verifications__canonical_final (
    id, execution_attempt_id, verification_no, status, normalizer_version,
    expected_json, actual_json, diff_json, verified_at_ms
)
SELECT
    id, execution_attempt_id, verification_no, status, normalizer_version,
    expected_json, actual_json, diff_json, verified_at_ms
FROM verifications;

DROP TABLE verifications;
ALTER TABLE verifications__canonical_final RENAME TO verifications;

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

DROP TRIGGER trg_approvals_active_action_guard_insert;
DROP TRIGGER trg_approvals_active_action_guard_update;
DROP TRIGGER trg_plans_inactive_approval_guard_update;
DROP TRIGGER trg_runs_active_approval_guard_update;

-- Creating or reactivating approval authority is legal only while the current
-- published Write Plan and its Run are ready to execute or verify that lineage.
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
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
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
          AND r.status IN ('WAITING_APPROVAL', 'VERIFYING')
    ) THEN RAISE(ABORT, 'NFR019_ACTIVE_APPROVAL_ACTION') END;
END;

CREATE TRIGGER trg_plans_inactive_approval_guard_update
BEFORE UPDATE OF status ON plans
WHEN NEW.status <> 'WAITING_APPROVAL'
AND EXISTS (
    SELECT 1
    FROM actions AS a
    JOIN approvals AS ap ON ap.action_id = a.id
    WHERE a.plan_id = OLD.id AND ap.status = 'ACTIVE'
)
BEGIN
    SELECT RAISE(ABORT, 'NFR019_PLAN_ACTIVE_APPROVAL');
END;

-- Existing authority may be suspended for confirmation, reauth, recovery, or
-- cancellation settlement, but it cannot survive planning/legacy READ/terminal states.
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

COMMIT;

PRAGMA foreign_keys = ON;
PRAGMA foreign_key_check;
