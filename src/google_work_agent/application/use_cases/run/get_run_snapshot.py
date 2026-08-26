"""Get one canonical persisted run snapshot through Repository/UoW boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionCommand,
    ActionStatus,
    EffectType,
    next_allowed_action_commands,
)
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.run.model import RunStatus, next_allowed_run_commands
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class ActionSnapshotResult:
    action_id: str
    tool_name: str
    status: str
    version: int
    effect_type: str
    approval_required: bool
    verification_policy: str
    risk: dict[str, object]
    next_allowed_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GetRunSnapshotQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class GetRunSnapshotResult:
    run_id: str
    conversation_id: str
    status: str
    version: int
    entry_mode: str
    requested_mode: str
    actual_runtime: str | None
    started_at_ms: int
    finished_at_ms: int | None
    active_plan: dict[str, object] | None
    actions: tuple[ActionSnapshotResult, ...]
    approvals: tuple[dict[str, object], ...]
    execution_status: dict[str, object]
    verification_summary: dict[str, object]
    recovery_summary: dict[str, object]
    result_kind: str | None
    next_allowed_commands: tuple[str, ...]
    snapshot_version: int


class GetRunSnapshotHandler:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def __call__(self, query: GetRunSnapshotQuery) -> GetRunSnapshotResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_snapshot(query.run_id)
            if run is None:
                return None
            plans = unit_of_work.plans.list_by_run(run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            action_records = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            actions = tuple(
                _action_snapshot(
                    action,
                    approval_allowed=(
                        plan is not None and plan.review_status is PlanReviewStatus.PASSED
                    ),
                )
                for action in action_records
            )
            approvals: list[dict[str, object]] = []
            verified_count = 0
            mismatch_count = 0
            for action in action_records:
                for approval in unit_of_work.approvals.list_by_action(action.id):
                    approvals.append(
                        {
                            "approval_id": approval.id,
                            "action_id": approval.action_id,
                            "status": approval.status.value,
                            "approved_at_ms": approval.approved_at_ms,
                            "expires_at_ms": approval.expires_at_ms,
                        }
                    )
                    for attempt in unit_of_work.execution_attempts.list_by_approval(approval.id):
                        for verification in unit_of_work.verifications.list_by_attempt(attempt.id):
                            verified_count += verification.status is VerificationStatus.VERIFIED
                            mismatch_count += verification.status is VerificationStatus.MISMATCH

        run_status = run.status
        terminal_statuses = {
            ActionStatus.VERIFIED.value,
            ActionStatus.REJECTED.value,
            ActionStatus.FAILED.value,
            ActionStatus.MISMATCH.value,
            ActionStatus.BLOCKED.value,
            ActionStatus.DEPENDENCY_BLOCKED.value,
            ActionStatus.CANCELLED.value,
        }
        active_plan = None
        if plan is not None:
            active_plan = {
                "plan_id": plan.id,
                "revision_no": plan.revision_no,
                "status": plan.status.value,
                "summary_text": plan.summary_text,
                "created_at_ms": plan.created_at_ms,
            }
        return GetRunSnapshotResult(
            run_id=run.id,
            conversation_id=run.conversation_id,
            status=run_status.value,
            version=run.version,
            entry_mode=run.entry_mode,
            requested_mode=run.requested_mode,
            actual_runtime=run.actual_runtime,
            started_at_ms=run.started_at_ms,
            finished_at_ms=run.finished_at_ms,
            active_plan=active_plan,
            actions=actions,
            approvals=tuple(approvals),
            execution_status={
                "action_count": len(actions),
                "terminal_action_count": sum(
                    action.status in terminal_statuses for action in actions
                ),
            },
            verification_summary={
                "verified_count": verified_count,
                "mismatch_count": mismatch_count,
            },
            recovery_summary={
                "unknown_result_action_count": sum(
                    action.status == ActionStatus.UNKNOWN_RESULT.value for action in actions
                )
            },
            result_kind=_cancel_result_kind(run_status=run_status, actions=actions),
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run_status)
            ),
            snapshot_version=1,
        )


def _action_snapshot(action: ActionRecord, *, approval_allowed: bool) -> ActionSnapshotResult:
    status = ActionStatus(action.status)
    effect_type = EffectType(action.effect_type)
    return ActionSnapshotResult(
        action_id=action.id,
        tool_name=action.tool_name,
        status=status.value,
        version=action.version,
        effect_type=effect_type.value,
        approval_required=action.approval_requirement == "REQUIRED",
        verification_policy=action.verification_policy,
        risk=action.risk,
        next_allowed_commands=tuple(
            item.value
            for item in next_allowed_action_commands(status, effect_type=effect_type)
            if approval_allowed or item is not ActionCommand.APPROVE_ACTION
        ),
    )


def _cancel_result_kind(
    *, run_status: RunStatus, actions: tuple[ActionSnapshotResult, ...]
) -> str | None:
    if run_status is not RunStatus.CANCELLED:
        return None
    has_success = any(action.status == ActionStatus.VERIFIED.value for action in actions)
    has_cancelled = any(action.status == ActionStatus.CANCELLED.value for action in actions)
    return "PARTIAL" if has_success and has_cancelled else "CANCELLED"
