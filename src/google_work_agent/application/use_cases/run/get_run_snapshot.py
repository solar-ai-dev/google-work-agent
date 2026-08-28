"""Get one canonical persisted run snapshot through Repository/UoW boundaries."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
    ProjectRecoveryOptionsQueryV1,
    ProjectRecoveryOptionsResultV1,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
    ProjectContextPreviewQueryV1,
    ProjectContextPreviewResultV1,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
    ProjectErrorActionsQueryV1,
)
from google_work_agent.application.use_cases.run.project_external_llm_transfer_scope import (
    ExternalLlmTransferScopeV1,
    ProjectExternalLlmTransferScopeHandler,
    ProjectExternalLlmTransferScopeQueryV1,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionCommand,
    ActionStatusV1,
    EffectType,
    next_allowed_action_commands,
)
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
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
    context_preview: ProjectContextPreviewResultV1 | None = None
    recovery_options: ProjectRecoveryOptionsResultV1 | None = None
    error_actions: tuple[str, ...] = ()
    external_llm_transfer_scope: ExternalLlmTransferScopeV1 | None = None


class GetRunSnapshotHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        project_context_preview: ProjectContextPreviewHandler | None = None,
        project_recovery_options: ProjectRecoveryOptionsHandler | None = None,
        project_error_actions: ProjectErrorActionsHandler | None = None,
        project_external_llm_transfer_scope: ProjectExternalLlmTransferScopeHandler
        | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._project_context_preview = project_context_preview
        self._project_recovery_options = project_recovery_options
        self._project_error_actions = project_error_actions
        self._project_external_llm_transfer_scope = project_external_llm_transfer_scope

    def __call__(self, query: GetRunSnapshotQuery) -> GetRunSnapshotResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_snapshot(query.run_id)
            if run is None:
                return None
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            action_records = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
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
                for approval in active_approval_tuple(unit_of_work.approvals, action.id):
                    approvals.append(
                        {
                            "approval_id": approval.id,
                            "action_id": approval.action_id,
                            "status": approval.status.value,
                            "approved_at_ms": approval.approved_at_ms,
                            "expires_at_ms": approval.expires_at_ms,
                        }
                    )
                for verification in unit_of_work.verifications.list_for_action(action.id):
                    verified_count += verification.status is VerificationStatus.VERIFIED
                    mismatch_count += verification.status is VerificationStatus.MISMATCH

        run_status = run.status
        terminal_statuses = {
            ActionStatusV1.VERIFIED.value,
            ActionStatusV1.REJECTED.value,
            ActionStatusV1.FAILED.value,
            ActionStatusV1.MISMATCH.value,
            ActionStatusV1.BLOCKED.value,
            ActionStatusV1.DEPENDENCY_BLOCKED.value,
            ActionStatusV1.CANCELLED.value,
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
        context_preview = self._optional_context_preview(run.id)
        recovery_options = self._optional_recovery_options(run.id, run_status)
        error_actions = (
            ()
            if self._project_error_actions is None
            else self._project_error_actions(
                ProjectErrorActionsQueryV1(
                    run_status=run_status.value,
                    recovery_allowed_resolutions=()
                    if recovery_options is None
                    else recovery_options.allowed_resolution_kinds,
                    reauth_required=run_status is RunStatusV1.REAUTH_REQUIRED,
                )
            ).action_ids
        )
        external_scope = (
            None
            if self._project_external_llm_transfer_scope is None
            else self._project_external_llm_transfer_scope(
                ProjectExternalLlmTransferScopeQueryV1(1, run.id)
            )
        )
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
                    action.status == ActionStatusV1.UNKNOWN_RESULT.value for action in actions
                )
            },
            result_kind=(
                None
                if run.terminal_result_kind is None
                else run.terminal_result_kind.value
            ),
            next_allowed_commands=tuple(
                item.value for item in next_allowed_run_commands(run_status)
            ),
            snapshot_version=1,
            context_preview=context_preview,
            recovery_options=recovery_options,
            error_actions=error_actions,
            external_llm_transfer_scope=external_scope,
        )

    def _optional_context_preview(self, run_id: str) -> ProjectContextPreviewResultV1 | None:
        if self._project_context_preview is None:
            return None
        try:
            return self._project_context_preview(ProjectContextPreviewQueryV1(run_id))
        except LookupError:
            return None

    def _optional_recovery_options(
        self, run_id: str, run_status: RunStatusV1
    ) -> ProjectRecoveryOptionsResultV1 | None:
        if (
            self._project_recovery_options is None
            or run_status is not RunStatusV1.RECOVERY_REQUIRED
        ):
            return None
        try:
            return self._project_recovery_options(ProjectRecoveryOptionsQueryV1(run_id))
        except LookupError:
            return None


def _action_snapshot(action: ActionRecord, *, approval_allowed: bool) -> ActionSnapshotResult:
    status = ActionStatusV1(action.status)
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
