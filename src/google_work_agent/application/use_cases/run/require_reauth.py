"""CommandResult-aware reauthentication boundary for write execution."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    resolve_existing_run_receipt as _resolve_existing_run_receipt,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteRunResponse,
)
from google_work_agent.application.use_cases.execution_attempt.write_recovery_contracts import (
    RequireWriteReauthCommand as RequireReauthCommand,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.require_reauth import transition_require_reauth
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.execution_attempt_repository import active_attempt_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class RequireReauthHandler:
    """Persist REAUTH_REQUIRED only when the Domain command is actually applied."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequireReauthCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RequireWriteReauth",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plans = tuple(
                plan
                for plan in current_plan_tuple(unit_of_work.plans, command.run_id)
                if plan.status is not PlanStatusV1.SUPERSEDED
            )
            plan = plans[0] if len(plans) == 1 else None
            actions = () if plan is None else unit_of_work.actions.list_for_plan(plan.id)
            approvals = tuple(
                approval
                for action in actions
                for approval in active_approval_tuple(unit_of_work.approvals, action.id)
            )
            attempts = tuple(
                attempt
                for approval in approvals
                for attempt in active_attempt_tuple(unit_of_work.execution_attempts, approval.id)
            )
            binding = unit_of_work.checkpoints.load_workflow_binding(run.id)
            checkpoint = (
                None
                if binding is None
                else unit_of_work.checkpoints.load_same_run_checkpoint(
                    run.id, binding.langgraph_thread_id
                )
            )
            target = None if checkpoint is None else checkpoint.registered_resume_target
            binding_is_current = bool(
                binding is not None
                and checkpoint is not None
                and checkpoint.run_id == run.id
                and checkpoint.langgraph_thread_id == binding.langgraph_thread_id
                and checkpoint.graph_profile == binding.graph_profile
                and checkpoint.graph_version == binding.graph_version
                and target is not None
                and target.graph_profile == binding.graph_profile
                and target.graph_version == binding.graph_version
            )
            try:
                next_status = transition_require_reauth(
                    run.status,
                    target_kind="" if target is None else target.kind,
                    target_stage=getattr(target, "stage_id", None),
                    binding_is_current=binding_is_current,
                    action_statuses=tuple(ActionStatusV1(action.status) for action in actions),
                    attempt_statuses=tuple(attempt.status for attempt in attempts),
                    has_legacy_read_executing=any(
                        EffectType(action.effect_type) is EffectType.READ
                        and ActionStatusV1(action.status) is ActionStatusV1.EXECUTING
                        for action in actions
                    ),
                    delivery_uncertain=any(
                        ActionStatusV1(action.status)
                        in {ActionStatusV1.EXECUTED, ActionStatusV1.UNKNOWN_RESULT}
                        for action in actions
                    )
                    or any(
                        attempt.status
                        in {
                            ExecutionAttemptStatusV1.EXECUTING,
                            ExecutionAttemptStatusV1.UNKNOWN_RESULT,
                            ExecutionAttemptStatusV1.SUCCEEDED,
                        }
                        for attempt in attempts
                    ),
                    cancel_intent_active=has_durable_cancel_intent(
                        unit_of_work.cancel_intents, run.id
                    ),
                )
            except RunTransitionRejected as error:
                response = WriteRunResponse(
                    False,
                    ResultCode.STATE_CONFLICT.value,
                    run.id,
                    run.status.value,
                    run.version,
                    None if plan is None else plan.id,
                    None if plan is None else plan.status.value,
                    conflict_detail=str(error),
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            if not unit_of_work.runs.update_if_version_and_status(
                run.id,
                run.version,
                frozenset({run.status}),
                {"status": next_status.value, "version": run.version + 1},
            ):
                raise RuntimeError("validated RequireReauth CAS failed")
            response = WriteRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=command.run_id,
                run_status=next_status.value,
                run_version=run.version + 1,
                plan_id=None if plan is None else plan.id,
                plan_status=None if plan is None else plan.status.value,
                result_kind="REAUTH_REQUIRED",
                conflict_detail=None,
            )
            if response.applied:
                trace_payload: dict[str, object] = {"safe_error_code": command.safe_error_code}
                audit_metadata: dict[str, object] = {"safe_error_code": command.safe_error_code}
                if command.mcp_request_id is not None:
                    trace_payload["mcp_request_id"] = command.mcp_request_id
                    audit_metadata["mcp_request_id"] = command.mcp_request_id
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=command.run_id,
                        action_id=command.action_id,
                        event_type="RUN_REAUTH_REQUIRED",
                        status=next_status.value,
                        duration_ms=None,
                        payload_json=dumps(trace_payload, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    _audit_event(
                        run_id=command.run_id,
                        action_id=command.action_id,
                        event_type="RUN_REAUTH_REQUIRED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata=audit_metadata,
                        created_at_ms=now_ms,
                    )
                )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                response.run_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


RequireReauthResult = WriteRunResponse

__all__ = ["RequireReauthCommand", "RequireReauthHandler", "RequireReauthResult"]
