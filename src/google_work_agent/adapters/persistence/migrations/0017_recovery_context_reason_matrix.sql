-- Migration 0017: final DB defense for the closed RecoveryContext reason matrix.
-- Applied migrations remain immutable; this forward migration validates new writes.

BEGIN IMMEDIATE;

CREATE TEMP TABLE recovery_context_reason_matrix_validation (
    is_valid INTEGER NOT NULL CHECK (is_valid = 1)
);

INSERT INTO recovery_context_reason_matrix_validation (is_valid)
SELECT CASE WHEN
    recovery_fingerprint <> ''
    AND (
        (reason = 'UNKNOWN_RESULT'
            AND scope = 'ACTION'
            AND action_id IS NOT NULL
            AND execution_attempt_id IS NOT NULL
            AND verification_id IS NULL
            AND observed_external_state_fingerprint IS NULL
            AND verification_input_fingerprint IS NULL
            AND contract_or_checkpoint_fingerprint IS NULL)
        OR
        (reason = 'VERIFICATION_MISMATCH'
            AND scope = 'ACTION'
            AND action_id IS NOT NULL
            AND execution_attempt_id IS NOT NULL
            AND verification_id IS NOT NULL
            AND observed_external_state_fingerprint IS NOT NULL
            AND verification_input_fingerprint IS NOT NULL
            AND contract_or_checkpoint_fingerprint IS NULL)
        OR
        (reason = 'CHECKPOINT_MISMATCH'
            AND scope = 'RUN'
            AND action_id IS NULL
            AND execution_attempt_id IS NULL
            AND verification_id IS NULL
            AND observed_external_state_fingerprint IS NULL
            AND verification_input_fingerprint IS NULL
            AND registered_resume_target_json IS NOT NULL
            AND contract_or_checkpoint_fingerprint IS NOT NULL)
        OR
        (reason = 'CONTRACT_VIOLATION'
            AND scope = 'RUN'
            AND action_id IS NULL
            AND execution_attempt_id IS NULL
            AND verification_id IS NULL
            AND observed_external_state_fingerprint IS NULL
            AND verification_input_fingerprint IS NULL
            AND contract_or_checkpoint_fingerprint IS NOT NULL)
    )
THEN 1 ELSE 0 END
FROM recovery_contexts;

DROP TABLE recovery_context_reason_matrix_validation;

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

COMMIT;

PRAGMA foreign_key_check;
