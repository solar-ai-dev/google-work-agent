"""Canonical persisted RefreshExpiredAction application boundary."""

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.write_persistence import require_plan_review
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.application.use_cases.run.resume_confirmation import ResumeTargetIssuer
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.action.model import Action, ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.refresh_expired_action import (
    transition_refresh_expired_action,
)
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.command_receipt.model import CommandReceiptStatus
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowHandoffStageV1,
)


@dataclass(frozen=True, slots=True)
class RefreshExpiredActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    expected_version: int
    fresh_source_snapshot: dict[str, object]
    fresh_source_snapshot_hash: str
    fresh_policy_version: str
    fresh_tool_schema_version: str
    fresh_risk: dict[str, object]


@dataclass(frozen=True, slots=True)
class RefreshExpiredActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    conflict_detail: str | None = None
    handoff_id: str | None = None


class RefreshExpiredActionHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        checkpoint_port: CheckpointPort,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        resume_target_registry: ResumeTargetIssuer,
        schedule_run_execution: Callable[[ScheduleRunExecutionCommand], RunExecutionAcceptedV1]
        | None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._checkpoint_port = checkpoint_port
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._resume_target_registry = resume_target_registry
        self._schedule_run_execution = schedule_run_execution

    def __call__(self, command: RefreshExpiredActionCommand) -> RefreshExpiredActionResult:
        if not all(
            (
                command.fresh_source_snapshot_hash,
                command.fresh_policy_version,
                command.fresh_tool_schema_version,
            )
        ):
            raise ValueError("RefreshExpiredAction requires freshly recomputed snapshots")
        if (
            calculate_canonical_json_hash(command.fresh_source_snapshot)
            != command.fresh_source_snapshot_hash
        ):
            raise ValueError("RefreshExpiredAction source snapshot hash mismatch")
        handoff_id: str | None = None
        with self._unit_of_work_factory() as unit_of_work:
            now_ms = self._now_ms()
            receipt = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if receipt is not None:
                if receipt.request_hash != command.request_hash:
                    action = _require_action(unit_of_work, command.action_id)
                    return RefreshExpiredActionResult(
                        False,
                        ResultCode.DUPLICATE_COMMAND.value,
                        action.id,
                        action.status,
                        action.version,
                        "command_id exists with a different request_hash",
                    )
                if (
                    receipt.response_json is not None
                    and receipt.status is not CommandReceiptStatus.RECEIVED
                ):
                    return RefreshExpiredActionResult(**loads(receipt.response_json))
                raise RuntimeError("RECEIVED RefreshExpiredAction receipt requires reconciliation")
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RefreshExpiredAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            plan = load_plan_record(unit_of_work.plans, action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            current = tuple(
                candidate
                for candidate in current_plan_tuple(unit_of_work.plans, plan.run_id)
                if candidate.status is not PlanStatusV1.SUPERSEDED
            )
            if unit_of_work.approvals.get_active_for_action(action.id) is not None:
                result = RefreshExpiredActionResult(
                    False,
                    ResultCode.STATE_CONFLICT.value,
                    action.id,
                    action.status,
                    action.version,
                    "RefreshExpiredAction requires zero ACTIVE Approval",
                )
            else:
                decision = transition_refresh_expired_action(
                    ActionStatusV1(action.status),
                    action.version,
                    command.expected_version,
                    effect_type=EffectType(action.effect_type),
                    plan_status=plan.status,
                    plan_is_current=len(current) == 1 and current[0].id == plan.id,
                )
                if decision.applied:
                    refreshed_risk = dict(command.fresh_risk)
                    refreshed_risk["refresh_snapshot"] = {
                        "source_snapshot_hash": command.fresh_source_snapshot_hash,
                        "policy_version": command.fresh_policy_version,
                        "tool_schema_version": command.fresh_tool_schema_version,
                    }
                    updated = update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=decision.current_status,
                        updated_at_ms=now_ms,
                        risk=refreshed_risk,
                    )
                    if updated is None:
                        raise RuntimeError("validated RefreshExpiredAction CAS failed")
                    self._refresh_target_resource_ref(
                        unit_of_work, action, command.fresh_source_snapshot, now_ms
                    )
                    require_plan_review(
                        unit_of_work,
                        plan.id,
                        command_id=command.command_id,
                        created_at_ms=now_ms,
                    )
                    unit_of_work.audits.append(
                        AuditEvent(
                            account_id=None,
                            run_id=plan.run_id,
                            action_id=action.id,
                            actor_type="SYSTEM",
                            actor_id="refresh_expired_action",
                            actor_display="RefreshExpiredAction",
                            event_type="ACTION_REFRESHED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata_json=dumps(
                                {
                                    "command_id": command.command_id,
                                    "source_snapshot_hash": command.fresh_source_snapshot_hash,
                                    "policy_version": command.fresh_policy_version,
                                    "tool_schema_version": command.fresh_tool_schema_version,
                                },
                                sort_keys=True,
                            ),
                            created_at_ms=now_ms,
                        )
                    )
                    handoff_id = self._stage_review_handoff(
                        unit_of_work, plan.run_id, command.command_id
                    )
                result = RefreshExpiredActionResult(
                    decision.applied,
                    decision.result_code.value,
                    action.id,
                    decision.current_status.value,
                    decision.current_version,
                    decision.conflict_detail,
                    handoff_id,
                )
            unit_of_work.command_receipts.store_result(
                command_id=command.command_id,
                applied=result.applied,
                result_code=ResultCode(result.result_code),
                result_version=result.action_version,
                response_json=dumps(asdict(result), sort_keys=True),
                completed_at_ms=now_ms,
            )
            unit_of_work.commit()
        if handoff_id is not None and self._schedule_run_execution is not None:
            self._schedule_run_execution(ScheduleRunExecutionCommand(handoff_id=handoff_id))
        return result

    @staticmethod
    def _refresh_target_resource_ref(
        unit_of_work: UnitOfWork,
        action: Action,
        snapshot: dict[str, object],
        now_ms: int,
    ) -> None:
        target_id = getattr(action, "target_resource_ref_id", None)
        if target_id is None or not snapshot:
            return
        current = unit_of_work.resource_refs.get(target_id)
        if current is None:
            raise RuntimeError("expired Action refresh target ResourceRef is missing")
        resource_id = snapshot.get("resource_id")
        resource_type = snapshot.get("resource_type")
        version = snapshot.get("version")
        if (
            resource_id != current.resource_id
            or resource_type != current.resource_type
            or not isinstance(version, str)
            or not version
        ):
            raise ValueError("fresh source snapshot does not match target ResourceRef")
        parent_id = snapshot.get("parent_id")
        if parent_id is not None and parent_id != current.parent_resource_id:
            raise ValueError("fresh source snapshot parent does not match target ResourceRef")
        unit_of_work.resource_refs.upsert_bound_ref(
            replace(current, version_token=version, captured_at_ms=now_ms)
        )

    def _stage_review_handoff(
        self, unit_of_work: UnitOfWork, run_id: str, trigger_command_id: str
    ) -> str:
        binding = self._checkpoint_port.load_workflow_binding(run_id)
        if binding is None:
            raise RuntimeError("expired Action refresh requires a workflow binding")
        checkpoint = self._checkpoint_port.load_same_run_checkpoint(
            run_id, binding.langgraph_thread_id
        )
        if checkpoint is None:
            raise RuntimeError("expired Action refresh requires a workflow checkpoint")
        target = self._resume_target_registry.issue_main_stage(
            binding.graph_profile, "REVIEW_ENTRY", binding.graph_version
        )
        handoff = unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                schema_version=1,
                handoff_id=self._id_factory(),
                trigger_command_id=trigger_command_id,
                execution=RunExecutionRefV1(
                    schema_version=1,
                    execution_kind="RESUME",
                    run_id=run_id,
                    langgraph_thread_id=binding.langgraph_thread_id,
                    graph_profile=binding.graph_profile,
                    graph_version=binding.graph_version,
                    requested_mode=binding.requested_mode,
                    resume_target=target,
                ),
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_generation=checkpoint.checkpoint_generation,
                control_kind="NONE",
                control=None,
                control_payload_hash=None,
            )
        )
        return handoff.handoff_id


def _require_action(unit_of_work: UnitOfWork, action_id: str) -> Action:
    action = unit_of_work.actions.get(action_id)
    if action is None:
        raise LookupError(f"action not found: {action_id}")
    return action


__all__ = [
    "RefreshExpiredActionCommand",
    "RefreshExpiredActionHandler",
    "RefreshExpiredActionResult",
]
