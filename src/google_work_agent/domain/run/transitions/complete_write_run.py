"""Canonical Run transition for complete write run."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.guards.complete_write_run import guard_complete_write_run
from google_work_agent.domain.run.model import (
    RunStatusV1,
    RunTransitionRejected,
    TerminalResultKindV1,
)

_PARTIAL_ACTION_STATUSES = frozenset(
    {
        ActionStatusV1.REJECTED,
        ActionStatusV1.CANCELLED,
        ActionStatusV1.BLOCKED,
        ActionStatusV1.DEPENDENCY_BLOCKED,
    }
)
_COMPLETE_ACTION_STATUSES = _PARTIAL_ACTION_STATUSES | {ActionStatusV1.VERIFIED}


def transition_complete_write_run(
    current_status: RunStatusV1,
    *,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    action_statuses: tuple[ActionStatusV1, ...],
    attempt_statuses: tuple[ExecutionAttemptStatusV1, ...],
    unresolved_required_fact_count: int,
    external_write_count: int,
    cancel_intent_active: bool,
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_complete_write_run(
        current_status,
        plan_status=plan_status,
        plan_is_current=plan_is_current,
        action_statuses=action_statuses,
        attempt_statuses=attempt_statuses,
        unresolved_required_fact_count=unresolved_required_fact_count,
        external_write_count=external_write_count,
        cancel_intent_active=cancel_intent_active,
    )
    return RunStatusV1.COMPLETED


def classify_complete_write_run_result(
    action_statuses: tuple[ActionStatusV1, ...],
) -> TerminalResultKindV1:
    """Classify only the closed Action facts admitted by CompleteWriteRun."""
    if not action_statuses or any(
        status not in _COMPLETE_ACTION_STATUSES for status in action_statuses
    ):
        raise RunTransitionRejected(
            "CompleteWriteRun result classification requires only canonical closed Actions"
        )
    if all(status is ActionStatusV1.VERIFIED for status in action_statuses):
        return TerminalResultKindV1.SUCCESS
    return TerminalResultKindV1.PARTIAL
