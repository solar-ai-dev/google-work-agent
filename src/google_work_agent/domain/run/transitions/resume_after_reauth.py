"""Canonical reauthentication resume transition."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.guards.resume_after_reauth import guard_resume_after_reauth
from google_work_agent.domain.run.model import RunStatusV1


def transition_resume_after_reauth(
    current_status: RunStatusV1,
    *,
    resume_status: RunStatusV1,
    target_kind: str,
    target_stage: str | None,
    binding_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    has_legacy_read_executing: bool,
    delivery_uncertain: bool,
    cancel_intent_active: bool,
) -> RunStatusV1:
    guard_resume_after_reauth(
        current_status,
        resume_status=resume_status,
        target_kind=target_kind,
        target_stage=target_stage,
        binding_is_current=binding_is_current,
        action_statuses=action_statuses,
        attempt_statuses=attempt_statuses,
        has_legacy_read_executing=has_legacy_read_executing,
        delivery_uncertain=delivery_uncertain,
        cancel_intent_active=cancel_intent_active,
    )
    return resume_status
