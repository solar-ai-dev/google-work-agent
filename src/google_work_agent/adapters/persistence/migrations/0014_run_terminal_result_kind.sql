ALTER TABLE runs
ADD COLUMN terminal_result_kind TEXT
CHECK (
    terminal_result_kind IS NULL
    OR terminal_result_kind IN ('SUCCESS', 'PARTIAL', 'BLOCKED', 'FAILED', 'CANCELLED')
);

UPDATE runs
SET terminal_result_kind = CASE
    WHEN status = 'BLOCKED' THEN 'BLOCKED'
    WHEN status = 'FAILED' THEN 'FAILED'
    WHEN status = 'CANCELLED' THEN
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM plans
                JOIN actions ON actions.plan_id = plans.id
                WHERE plans.run_id = runs.id
                  AND actions.status IN ('EXECUTED', 'VERIFIED', 'MISMATCH')
            ) OR EXISTS (
                SELECT 1
                FROM plans
                JOIN actions ON actions.plan_id = plans.id
                JOIN approvals ON approvals.action_id = actions.id
                JOIN execution_attempts ON execution_attempts.approval_id = approvals.id
                WHERE plans.run_id = runs.id
                  AND execution_attempts.status = 'SUCCEEDED'
            ) THEN 'PARTIAL'
            ELSE 'CANCELLED'
        END
    WHEN status = 'COMPLETED' THEN
        CASE
            WHEN EXISTS (
                SELECT 1
                FROM plans
                JOIN actions ON actions.plan_id = plans.id
                WHERE plans.run_id = runs.id
                  AND actions.status IN (
                      'FAILED', 'MISMATCH', 'REJECTED', 'BLOCKED',
                      'CANCELLED', 'DEPENDENCY_BLOCKED'
                  )
            ) THEN 'PARTIAL'
            ELSE 'SUCCESS'
        END
    ELSE NULL
END
WHERE status IN ('COMPLETED', 'BLOCKED', 'FAILED', 'CANCELLED');

CREATE UNIQUE INDEX ux_messages_terminal_assistant_per_run
ON messages(run_id)
WHERE role = 'ASSISTANT' AND run_id IS NOT NULL;
