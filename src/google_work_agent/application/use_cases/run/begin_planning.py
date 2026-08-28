"""Canonical application use case for entering or re-entering Run planning."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import update_plan_record
from google_work_agent.application.use_cases.action.write_persistence import revoke_active_approvals
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.command_receipt.model import CommandReceipt as CommandReceiptRecord
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import (
    RunStatusV1,
    RunTransitionRejected,
    next_allowed_run_commands,
)
from google_work_agent.domain.run.transitions.begin_planning import transition_begin_planning
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    ContextAdjustmentControlV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)

_PUBLISHED_REENTRY = frozenset({RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING})
_UNRESOLVED_EXTERNAL_EFFECTS = frozenset(
    {
        ActionStatusV1.EXECUTING,
        ActionStatusV1.UNKNOWN_RESULT,
        ActionStatusV1.EXECUTED,
        ActionStatusV1.MISMATCH,
    }
)


@dataclass(frozen=True, slots=True)
class BeginPlanningCommand:
    run_id: str
    expected_version: int
    command_id: str
    request_hash: str
    plan_id: str | None = None
    expected_review_version: int | None = None
    expected_retrieval_revision: int | None = None
    context_adjustment: ContextAdjustmentControlV1 | None = None


@dataclass(frozen=True, slots=True)
class BeginPlanningResult:
    applied: bool
    result_code: str
    current_status: str
    current_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None
    handoff_id: str | None = None


class BeginPlanningHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        resume_target_registry: ResumeTargetIssuer,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._resume_target_registry = resume_target_registry

    def __call__(self, command: BeginPlanningCommand) -> BeginPlanningResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._replay(unit_of_work, command, existing)
            run = unit_of_work.runs.get(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="BeginPlanning",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            result = self._apply(unit_of_work, command, run.status, run.version, now_ms)
            if result.applied:
                unit_of_work.audits.append(_audit(command, result, now_ms))
            _finish_receipt(unit_of_work, command.command_id, result, now_ms)
            unit_of_work.commit()
            return result

    def _apply(
        self,
        unit_of_work: UnitOfWork,
        command: BeginPlanningCommand,
        status: RunStatusV1,
        version: int,
        now_ms: int,
    ) -> BeginPlanningResult:
        if version != command.expected_version:
            return _result(False, ResultCode.VERSION_CONFLICT, status, version, "version mismatch")

        published_reentry = status in _PUBLISHED_REENTRY
        context_adjustment = command.context_adjustment is not None
        plan = (
            self._current_plan(unit_of_work, command)
            if published_reentry or context_adjustment
            else None
        )
        actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
        action_statuses = tuple(ActionStatusV1(action.status) for action in actions)
        active_approvals = sum(
            1
            for action in actions
            if (approval := unit_of_work.approvals.get_active_for_action(action.id)) is not None
            and approval.status is ApprovalStatusV1.ACTIVE
        )
        unresolved_effects = sum(
            1 for action_status in action_statuses if action_status in _UNRESOLVED_EXTERNAL_EFFECTS
        )
        revision_error = self._revision_error(
            unit_of_work=unit_of_work,
            command=command,
            plan=plan,
            published_reentry=published_reentry,
        )
        if revision_error is not None:
            return _result(False, ResultCode.VERSION_CONFLICT, status, version, revision_error)

        try:
            next_status = transition_begin_planning(
                status,
                durable_review_disposition=None if plan is None else plan.review_disposition,
                user_context_adjustment=context_adjustment,
                has_current_plan=plan is not None,
                current_action_statuses=action_statuses,
                active_approval_count=active_approvals,
                unresolved_external_effect_count=unresolved_effects,
                expected_revisions_match=True,
            )
        except RunTransitionRejected as error:
            return _result(False, ResultCode.STATE_CONFLICT, status, version, str(error))

        applied = unit_of_work.runs.update_if_version_and_status(
            command.run_id,
            command.expected_version,
            frozenset({status}),
            {"status": next_status.value, "version": version + 1, "finished_at_ms": None},
        )
        if not applied:
            current = unit_of_work.runs.get(command.run_id)
            if current is None:
                raise LookupError(f"run not found: {command.run_id}")
            return _result(
                False,
                ResultCode.VERSION_CONFLICT,
                current.status,
                current.version,
                "compare-and-set rejected the transition",
            )

        if plan is not None:
            for action in actions:
                revoke_active_approvals(unit_of_work, action.id)
            if (
                update_plan_record(
                    unit_of_work,
                    plan.id,
                    expected_status=plan.status,
                    next_status=PlanStatusV1.SUPERSEDED,
                )
                is None
            ):
                raise RuntimeError(f"validated Plan supersession CAS failed: {plan.id}")

        handoff_id = None
        if command.context_adjustment is not None:
            handoff_id = self._stage_context_adjustment(
                unit_of_work=unit_of_work,
                command=command,
            )
        return _result(
            True,
            ResultCode.TRANSITION_APPLIED,
            next_status,
            version + 1,
            handoff_id=handoff_id,
        )

    @staticmethod
    def _current_plan(unit_of_work: UnitOfWork, command: BeginPlanningCommand) -> PlanRecord | None:
        if command.plan_id is None:
            return None
        plan = unit_of_work.plans.load_bundle(command.plan_id)
        return (
            plan
            if plan is not None
            and plan.run_id == command.run_id
            and plan.status is PlanStatusV1.WAITING_APPROVAL
            else None
        )

    @staticmethod
    def _revision_error(
        *,
        unit_of_work: UnitOfWork,
        command: BeginPlanningCommand,
        plan: PlanRecord | None,
        published_reentry: bool,
    ) -> str | None:
        if (published_reentry or command.context_adjustment is not None) and plan is None:
            return "current Plan does not match the requested Plan"
        if published_reentry and command.context_adjustment is None:
            if command.expected_review_version is None:
                return "expected_review_version is required for published re-entry"
            if plan is None or plan.review_version != command.expected_review_version:
                return "review version mismatch"
        if command.context_adjustment is not None:
            if command.expected_retrieval_revision is None:
                return "expected_retrieval_revision is required for context adjustment"
            head = unit_of_work.checkpoints.load_retrieval_head(command.run_id)
            if head is None or head.retrieval_revision != command.expected_retrieval_revision:
                return "retrieval revision mismatch"
        return None

    def _stage_context_adjustment(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: BeginPlanningCommand,
    ) -> str:
        control = command.context_adjustment
        if control is None:
            raise AssertionError("context adjustment control is required")
        head = unit_of_work.checkpoints.load_retrieval_head(command.run_id)
        binding = unit_of_work.checkpoints.load_workflow_binding(command.run_id)
        if head is None or binding is None:
            raise RuntimeError(
                "context adjustment requires durable workflow binding and retrieval head"
            )
        handoff_id = self._id_factory()
        target = self._resume_target_registry.issue_main_stage(
            binding.graph_profile,
            "RETRIEVAL_ENTRY",
            binding.graph_version,
        )
        control_json = dumps(asdict(control), sort_keys=True, separators=(",", ":"))
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=handoff_id,
                trigger_command_id=command.command_id,
                execution=RunExecutionRefV1(
                    schema_version=1,
                    execution_kind="RESUME",
                    run_id=command.run_id,
                    langgraph_thread_id=binding.langgraph_thread_id,
                    graph_profile=binding.graph_profile,
                    graph_version=binding.graph_version,
                    requested_mode=binding.requested_mode,
                    resume_target=target,
                ),
                checkpoint_id=head.checkpoint_id,
                checkpoint_generation=head.checkpoint_generation,
                control_kind="CONTEXT_ADJUSTMENT",
                control=control,
                control_payload_hash=hashlib.sha256(control_json.encode("utf-8")).hexdigest(),
            )
        )
        return handoff_id

    @staticmethod
    def _replay(
        unit_of_work: UnitOfWork,
        command: BeginPlanningCommand,
        receipt: CommandReceiptRecord,
    ) -> BeginPlanningResult:
        if receipt.request_hash != command.request_hash:
            run = unit_of_work.runs.get(command.run_id)
            return _result(
                False,
                ResultCode.DUPLICATE_COMMAND,
                RunStatusV1.CREATED if run is None else run.status,
                0 if run is None else run.version,
                "command_id already exists with a different request_hash",
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
        payload = loads(receipt.response_json)
        payload["next_allowed_commands"] = tuple(payload.get("next_allowed_commands", ()))
        return BeginPlanningResult(**payload)


def _result(
    applied: bool,
    result_code: ResultCode,
    status: RunStatusV1,
    version: int,
    conflict_detail: str | None = None,
    handoff_id: str | None = None,
) -> BeginPlanningResult:
    return BeginPlanningResult(
        applied=applied,
        result_code=result_code.value,
        current_status=status.value,
        current_version=version,
        next_allowed_commands=tuple(command.value for command in next_allowed_run_commands(status)),
        conflict_detail=conflict_detail,
        handoff_id=handoff_id,
    )


def _audit(
    command: BeginPlanningCommand, result: BeginPlanningResult, now_ms: int
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=command.run_id,
        action_id=None,
        actor_type="SYSTEM",
        actor_id="run_lifecycle",
        actor_display="Run lifecycle",
        event_type="RUN_PLANNING_STARTED",
        outcome=result.result_code,
        metadata_json=dumps(
            {
                "command_id": command.command_id,
                "plan_id": command.plan_id,
                "context_adjustment": command.context_adjustment is not None,
                "handoff_id": result.handoff_id,
            },
            sort_keys=True,
        ),
        created_at_ms=now_ms,
    )


def _finish_receipt(
    unit_of_work: UnitOfWork, command_id: str, result: BeginPlanningResult, now_ms: int
) -> None:
    unit_of_work.command_receipts.store_result(
        command_id=command_id,
        applied=result.applied,
        result_code=ResultCode(result.result_code),
        result_version=result.current_version,
        response_json=dumps(asdict(result), sort_keys=True),
        completed_at_ms=now_ms,
    )
