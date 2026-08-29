"""Guard for require reauth."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected, require_status

_ALLOWED = frozenset(
    {
        RunStatusV1.ANALYZING,
        RunStatusV1.RETRIEVING,
        RunStatusV1.PLANNING,
        RunStatusV1.WAITING_APPROVAL,
        RunStatusV1.EXECUTING,
        RunStatusV1.VERIFYING,
        RunStatusV1.RECOVERY_REQUIRED,
        RunStatusV1.CANCEL_REQUESTED,
    }
)


def guard_require_reauth(
    current_status: RunStatusV1,
    *,
    target_kind: str,
    target_stage: str | None,
    binding_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    has_legacy_read_executing: bool,
    delivery_uncertain: bool,
    cancel_intent_active: bool,
) -> None:
    """Reject a require reauth request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "require_reauth")
    if not binding_is_current:
        raise RunTransitionRejected("RequireReauth requires current registered target binding")
    if target_kind == "AGENT_NODE":
        if current_status not in {
            RunStatusV1.ANALYZING,
            RunStatusV1.RETRIEVING,
            RunStatusV1.PLANNING,
        }:
            raise RunTransitionRejected("AGENT_NODE reauth target does not match Run phase")
        return
    if target_kind != "MAIN_CONTROL" or target_stage is None:
        raise RunTransitionRejected("RequireReauth requires a registered resume target")
    if target_stage == "CANCEL_RESOLUTION":
        if current_status is not RunStatusV1.CANCEL_REQUESTED or not cancel_intent_active:
            raise RunTransitionRejected(
                "CANCEL_RESOLUTION reauth requires durable CANCEL_REQUESTED authority"
            )
        return
    if target_stage == "PREFLIGHT":
        has_dispatched_action = any(
            status
            in {
                ActionStatusV1.EXECUTING,
                ActionStatusV1.EXECUTED,
                ActionStatusV1.UNKNOWN_RESULT,
                ActionStatusV1.MISMATCH,
            }
            for status in action_statuses
        )
        if (
            current_status is not RunStatusV1.WAITING_APPROVAL
            or has_dispatched_action
            or attempt_statuses
            or delivery_uncertain
            or cancel_intent_active
        ):
            raise RunTransitionRejected("PREFLIGHT reauth requires zero dispatched Write fact")
        return
    if target_stage == "READ_EXECUTION":
        if (
            current_status is not RunStatusV1.EXECUTING
            or not has_legacy_read_executing
            or attempt_statuses
            or cancel_intent_active
        ):
            raise RunTransitionRejected("READ_EXECUTION reauth requires safe Legacy READ facts")
        return
    if target_stage == "VERIFICATION":
        has_post_dispatch = any(
            status is ActionStatusV1.EXECUTED for status in action_statuses
        ) or any(status is ExecutionAttemptStatusV1.SUCCEEDED for status in attempt_statuses)
        if current_status is not RunStatusV1.VERIFYING and not has_post_dispatch:
            raise RunTransitionRejected("VERIFICATION reauth requires durable post-dispatch fact")
        return
    if target_stage == "RECOVERY":
        has_recovery_fact = (
            current_status is RunStatusV1.RECOVERY_REQUIRED
            or any(
                status in {ActionStatusV1.UNKNOWN_RESULT, ActionStatusV1.MISMATCH}
                for status in action_statuses
            )
            or any(status is ExecutionAttemptStatusV1.UNKNOWN_RESULT for status in attempt_statuses)
        )
        if not has_recovery_fact:
            raise RunTransitionRejected("RECOVERY reauth requires durable recovery fact")
        return
    raise RunTransitionRejected("resume target is not legal for Reauth")
