"""Canonical Run transition for require reauth."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.guards.require_reauth import guard_require_reauth
from google_work_agent.domain.run.model import RunStatusV1


def transition_require_reauth(
    current_status: RunStatusV1,
    *,
    target_kind: str,
    target_stage: str | None,
    binding_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    delivery_uncertain: bool,
    cancel_intent_active: bool,
    has_legacy_read_executing: bool = False,
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_require_reauth(
        current_status,
        target_kind=target_kind,
        target_stage=target_stage,
        binding_is_current=binding_is_current,
        action_statuses=action_statuses,
        attempt_statuses=attempt_statuses,
        delivery_uncertain=delivery_uncertain,
        cancel_intent_active=cancel_intent_active,
        has_legacy_read_executing=has_legacy_read_executing,
    )
    return RunStatusV1.REAUTH_REQUIRED
