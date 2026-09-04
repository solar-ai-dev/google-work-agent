"""Build one canonical persisted Run UI snapshot through Repository/UoW boundaries."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from json import loads

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
)
from google_work_agent.application.use_cases.action.task_duplicates import TASK_CREATE_TOOL
from google_work_agent.application.use_cases.execution_attempt.project_delivery_certainty import (
    DeliveryCertaintyV1,
    project_latest_delivery_certainty,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.application.use_cases.recovery.project_recovery_options import (
    ProjectRecoveryOptionsHandler,
    ProjectRecoveryOptionsQueryV1,
    ProjectRecoveryOptionsResultV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
    validate_run_budget_v2,
)
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
    ProjectContextPreviewQueryV1,
    ProjectContextPreviewResultV1,
)
from google_work_agent.application.use_cases.run.project_error_actions import (
    ProjectErrorActionsHandler,
    ProjectErrorActionsQueryV1,
    ProjectErrorActionsResultV1,
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
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.domain.plan.model import PlanReviewStatus
from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


@dataclass(frozen=True, slots=True)
class RunSnapshotRunV1:
    run_id: str
    conversation_id: str
    status: str
    version: int
    entry_mode: str
    requested_mode: str
    actual_runtime: str | None
    started_at_ms: int
    finished_at_ms: int | None
    next_allowed_commands: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunSnapshotMessageV1:
    schema_version: int
    id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int


@dataclass(frozen=True, slots=True)
class PendingInterruptV1:
    schema_version: int
    interrupt_id: str
    semantic_owner_id: str
    question: str
    options: tuple[str, ...]
    response_mode: str


@dataclass(frozen=True, slots=True)
class ActionSnapshotResult:
    action_id: str
    tool_name: str
    arguments: dict[str, object]
    status: str
    version: int
    effect_type: str
    approval_required: bool
    verification_policy: str
    risk: dict[str, object]
    next_allowed_commands: tuple[str, ...]
    required_acknowledgements: tuple[str, ...]
    editable_fields: tuple[str, ...]
    attachment_allowed: bool
    delivery_certainty: DeliveryCertaintyV1 | None


@dataclass(frozen=True, slots=True)
class GetRunSnapshotQuery:
    run_id: str


@dataclass(frozen=True, slots=True)
class GetExecutionContextQuery:
    """Owner-local workflow admission projection input."""

    run_id: str


@dataclass(frozen=True, slots=True)
class GetExecutionContextResult:
    run_id: str
    conversation_id: str
    workflow_key: str
    entry_mode: str
    requested_mode: str
    status: str
    version: int
    request_text: str
    user_message_id: str | None
    selected_resource_ids: tuple[str, ...]
    run_budget: RunBudgetV2
    selected_resources: tuple[SelectedResourceRef, ...] = ()


@dataclass(frozen=True, slots=True)
class GetRunSnapshotResult:
    run: RunSnapshotRunV1
    messages: tuple[RunSnapshotMessageV1, ...]
    current_plan: dict[str, object] | None
    actions: tuple[ActionSnapshotResult, ...]
    context_preview: ProjectContextPreviewResultV1 | None
    pending_interrupt: PendingInterruptV1 | None
    recovery: ProjectRecoveryOptionsResultV1 | None
    error: ProjectErrorActionsResultV1 | None
    external_llm_transfer_scope: ExternalLlmTransferScopeV1 | None
    terminal_result_kind: str
    projection_version: int
    approvals: tuple[dict[str, object], ...]
    execution_status: dict[str, object]
    verification_summary: dict[str, object]
    recovery_summary: dict[str, object]

    @property
    def run_id(self) -> str:
        return self.run.run_id

    @property
    def status(self) -> str:
        return self.run.status


class GetRunSnapshotHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        project_context_preview: ProjectContextPreviewHandler | None = None,
        project_recovery_options: ProjectRecoveryOptionsHandler | None = None,
        project_error_actions: ProjectErrorActionsHandler | None = None,
        project_external_llm_transfer_scope: ProjectExternalLlmTransferScopeHandler | None = None,
        resolve_pending_confirmation: Callable[[str], Mapping[str, object] | None] | None = None,
        tool_registry: SignedToolRegistry | None = None,
        message_limit: int = 200,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._project_context_preview = project_context_preview
        self._project_recovery_options = project_recovery_options
        self._project_error_actions = project_error_actions
        self._project_external_llm_transfer_scope = project_external_llm_transfer_scope
        self._resolve_pending_confirmation = resolve_pending_confirmation
        self._tool_registry = tool_registry
        self._message_limit = message_limit

    def __call__(self, query: GetRunSnapshotQuery) -> GetRunSnapshotResult | None:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_snapshot(query.run_id)
            if run is None:
                return None
            message_records = _messages_for_run(
                unit_of_work,
                conversation_id=run.conversation_id,
                run_id=run.id,
                limit=self._message_limit,
            )
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.id), default=None)
            action_records = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            actions = tuple(
                _action_snapshot(
                    action,
                    approval_allowed=(
                        plan is not None and plan.review_status is PlanReviewStatus.PASSED
                    ),
                    tool_registry=self._tool_registry,
                    delivery_certainty=project_latest_delivery_certainty(unit_of_work, action.id),
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

        terminal_statuses = {
            ActionStatusV1.VERIFIED.value,
            ActionStatusV1.REJECTED.value,
            ActionStatusV1.FAILED.value,
            ActionStatusV1.MISMATCH.value,
            ActionStatusV1.BLOCKED.value,
            ActionStatusV1.DEPENDENCY_BLOCKED.value,
            ActionStatusV1.CANCELLED.value,
        }
        current_plan = None
        if plan is not None:
            current_plan = {
                "plan_id": plan.id,
                "revision_no": plan.revision_no,
                "status": plan.status.value,
                "summary_text": plan.summary_text,
                "created_at_ms": plan.created_at_ms,
            }
        return GetRunSnapshotResult(
            run=RunSnapshotRunV1(
                run_id=run.id,
                conversation_id=run.conversation_id,
                status=run.status.value,
                version=run.version,
                entry_mode=run.entry_mode,
                requested_mode=run.requested_mode,
                actual_runtime=run.actual_runtime,
                started_at_ms=run.started_at_ms,
                finished_at_ms=run.finished_at_ms,
                next_allowed_commands=tuple(
                    item.value for item in next_allowed_run_commands(run.status)
                ),
            ),
            messages=tuple(
                RunSnapshotMessageV1(
                    1,
                    record.id,
                    record.run_id,
                    record.role,
                    record.content,
                    record.created_at_ms,
                )
                for record in message_records
            ),
            current_plan=current_plan,
            actions=actions,
            context_preview=self._optional_context_preview(run.id),
            pending_interrupt=self._optional_pending_interrupt(run.id, run.status),
            recovery=self._optional_recovery_options(run.id, run.status),
            error=self._optional_error(run.id),
            external_llm_transfer_scope=self._optional_external_scope(run.id),
            terminal_result_kind=(
                "NONE" if run.terminal_result_kind is None else run.terminal_result_kind.value
            ),
            projection_version=1,
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
        )

    def execution_context(
        self, query: GetExecutionContextQuery
    ) -> GetExecutionContextResult | None:
        """Project workflow input through the canonical Run snapshot query owner."""

        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(query.run_id)
            if run is None:
                return None
            messages = _messages_for_run(
                unit_of_work,
                conversation_id=run.conversation_id,
                run_id=run.id,
                limit=self._message_limit,
            )
            resources = unit_of_work.resource_refs.list_for_run_bounded(query.run_id, limit=200)
        first_user_message = next((item for item in messages if item.role == "USER"), None)
        return GetExecutionContextResult(
            run_id=run.id,
            conversation_id=run.conversation_id,
            workflow_key=run.langgraph_thread_id,
            entry_mode=run.entry_mode,
            requested_mode=run.requested_mode,
            status=run.status.value,
            version=run.version,
            request_text="" if first_user_message is None else first_user_message.content,
            user_message_id=None if first_user_message is None else first_user_message.id,
            selected_resource_ids=tuple(record.resource_id for record in resources),
            run_budget=validate_run_budget_v2(loads(run.budget_json)),
            selected_resources=tuple(_selected_resource_ref(record) for record in resources),
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

    def _optional_error(self, run_id: str) -> ProjectErrorActionsResultV1 | None:
        if self._project_error_actions is None:
            return None
        return self._project_error_actions(ProjectErrorActionsQueryV1(run_id))

    def _optional_external_scope(self, run_id: str) -> ExternalLlmTransferScopeV1 | None:
        if self._project_external_llm_transfer_scope is None:
            return None
        return self._project_external_llm_transfer_scope(
            ProjectExternalLlmTransferScopeQueryV1(1, run_id)
        )

    def _optional_pending_interrupt(
        self, run_id: str, run_status: RunStatusV1
    ) -> PendingInterruptV1 | None:
        if (
            self._resolve_pending_confirmation is None
            or run_status is not RunStatusV1.WAITING_CONFIRMATION
        ):
            return None
        pending = self._resolve_pending_confirmation(run_id)
        if pending is None:
            return None
        options = pending.get("options")
        normalized_options = (
            tuple(str(item) for item in options) if isinstance(options, list) else ()
        )
        return PendingInterruptV1(
            schema_version=1,
            interrupt_id=str(pending["interrupt_id"]),
            semantic_owner_id=str(pending["semantic_owner_id"]),
            question=str(pending["question"]),
            options=normalized_options,
            response_mode="OPTION" if normalized_options else "FREE_TEXT",
        )


def _action_snapshot(
    action: ActionRecord,
    *,
    approval_allowed: bool,
    tool_registry: SignedToolRegistry | None,
    delivery_certainty: DeliveryCertaintyV1 | None,
) -> ActionSnapshotResult:
    status = ActionStatusV1(action.status)
    effect_type = EffectType(action.effect_type)
    arguments = loads(action.arguments_json)
    if not isinstance(arguments, dict):
        raise ValueError("persisted Action arguments must be an object")
    editable_fields: tuple[str, ...] = ()
    if tool_registry is not None:
        entry = tool_registry.get_required(action.connector_id, action.tool_name)
        editable_fields = tuple(sorted(entry.modify_patchable_fields))
    required_acknowledgements = _required_acknowledgements(action)
    approval_allowed = approval_allowed and _approval_is_presentable(action)
    return ActionSnapshotResult(
        action_id=action.id,
        tool_name=action.tool_name,
        arguments=arguments,
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
        required_acknowledgements=required_acknowledgements,
        editable_fields=editable_fields,
        attachment_allowed="attachments" in editable_fields,
        delivery_certainty=delivery_certainty,
    )


def _required_acknowledgements(action: ActionRecord) -> tuple[str, ...]:
    required: list[str] = []
    duplicate = action.risk.get("duplicate")
    if (
        action.tool_name == TASK_CREATE_TOOL
        and isinstance(duplicate, dict)
        and duplicate.get("decision")
        in {
            "SIMILAR_CANDIDATE",
            "CLEAR_DUPLICATE",
        }
    ):
        required.append("TASK_DUPLICATE")
    conflict = action.risk.get("calendar_conflict")
    if (
        action.tool_name in CALENDAR_CONFLICT_TOOLS
        and isinstance(conflict, dict)
        and conflict.get("decision") in {"WARNING", "HARD_CONFLICT"}
    ):
        required.append("CALENDAR_CONFLICT")
    return tuple(required)


def _approval_is_presentable(action: ActionRecord) -> bool:
    if action.tool_name not in CALENDAR_CONFLICT_TOOLS:
        return True
    feasibility = action.risk.get("feasibility")
    return not (isinstance(feasibility, dict) and feasibility.get("decision") == "INFEASIBLE")


def _messages_for_run(
    unit_of_work: UnitOfWork,
    *,
    conversation_id: str,
    run_id: str,
    limit: int,
) -> tuple[MessageRecord, ...]:
    """Project one Run's messages via the exact Conversation keyset query."""

    cursor: str | None = None
    matches: list[MessageRecord] = []
    remaining_scan_budget = limit * 10
    while remaining_scan_budget > 0 and len(matches) < limit:
        page_size = min(limit, remaining_scan_budget)
        page, cursor = unit_of_work.messages.list_by_conversation_keyset(
            conversation_id=conversation_id,
            cursor=cursor,
            page_size=page_size,
        )
        matches.extend(message for message in page if message.run_id == run_id)
        remaining_scan_budget -= len(page)
        if cursor is None or not page:
            break
    return tuple(sorted(matches[:limit], key=lambda item: (item.created_at_ms, item.id)))


def _selected_resource_ref(value: ResourceRef) -> SelectedResourceRef:
    durable_type = value.resource_type
    source, projected_type = {
        "gmail_thread": ("GMAIL", "THREAD"),
        "gmail_message": ("GMAIL", "MESSAGE"),
        "gmail_attachment": ("GMAIL", "ATTACHMENT"),
        "gmail_draft": ("GMAIL", "DRAFT"),
        "task_list": ("TASKS", "TASK_LIST"),
        "task": ("TASKS", "TASK"),
        "calendar": ("CALENDAR", "CALENDAR"),
        "calendar_event": ("CALENDAR", "EVENT"),
        "calendar_freebusy": ("CALENDAR", "FREEBUSY"),
    }[durable_type]
    return SelectedResourceRef(
        source=source,
        resource_type=projected_type,
        resource_id=value.resource_id,
        parent_resource_id=value.parent_resource_id,
    )


__all__ = [
    "ActionSnapshotResult",
    "GetExecutionContextQuery",
    "GetExecutionContextResult",
    "GetRunSnapshotHandler",
    "GetRunSnapshotQuery",
    "GetRunSnapshotResult",
    "PendingInterruptV1",
    "RunSnapshotMessageV1",
    "RunSnapshotRunV1",
]
