"""Guard for restoring the persisted pre-reauth safe Run phase."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.guards.require_reauth import guard_require_reauth
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected

_SAFE = frozenset(
    {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.EXECUTING,
        RunStatusV1.VERIFYING,
        RunStatusV1.CANCEL_REQUESTED,
        RunStatusV1.RECOVERY_REQUIRED,
    }
)


def guard_resume_after_reauth(
    current_status: RunStatusV1,
    *,
    resume_status: RunStatusV1,
    target_kind: str,
    target_stage: str | None,
    binding_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    delivery_uncertain: bool,
    cancel_intent_active: bool,
    has_legacy_read_executing: bool = False,
) -> None:
    if current_status is not RunStatusV1.REAUTH_REQUIRED:
        raise RunTransitionRejected("resume_after_reauth requires REAUTH_REQUIRED")
    if resume_status not in _SAFE:
        raise RunTransitionRejected("resume_after_reauth requires a persisted safe status")
    guard_require_reauth(
        resume_status,
        target_kind=target_kind,
        target_stage=target_stage,
        binding_is_current=binding_is_current,
        action_statuses=action_statuses,
        attempt_statuses=attempt_statuses,
        delivery_uncertain=delivery_uncertain,
        cancel_intent_active=cancel_intent_active,
        has_legacy_read_executing=has_legacy_read_executing,
    )
