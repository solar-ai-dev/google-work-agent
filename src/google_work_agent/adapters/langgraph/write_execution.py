"""LangGraph translation for approved action execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.main.state import (
    ExecutionSummaryV1,
    GraphState,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.write_reconciliation import (
    ReconcileAggregate,
    reconcile_write_conflict,
)
from google_work_agent.application.use_cases.execution_attempt.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
    WriteExecutionPhaseResult,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.run.model import RunStatusV1, next_allowed_run_commands


class WriteExecutionNode:
    """Translate one approved Plan execution into LangGraph state updates."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str],
        request_hash: Callable[[dict[str, object]], str],
        should_stop_for_cancel: Callable[[str], bool],
        list_actions: Callable[[str], tuple[ActionRecord, ...]],
        has_independent_executable_action: Callable[[str, str], bool],
        execute_read_only_plan: Callable[[GraphState, str, tuple[ActionRecord, ...]], GraphState],
        execution_phase: WriteExecutionPhaseCoordinator,
        has_persisted_cancel_intent: Callable[[str], bool],
    ) -> None:
        self._id_factory = id_factory
        self._request_hash = request_hash
        self._should_stop_for_cancel = should_stop_for_cancel
        self._list_actions = list_actions
        self._has_independent_executable_action = has_independent_executable_action
        self._execute_read_only_plan = execute_read_only_plan
        self._execution_phase = execution_phase
        self._has_persisted_cancel_intent = has_persisted_cancel_intent

    def preflight(self, state: Mapping[str, object]) -> dict[str, object]:
        """Project freshness/Claim readiness without invoking connector write."""

        run_id = cast(str, state["run_id"])
        plan_id = self._required_string(state.get("approved_plan_id"), "approved_plan_id")
        actions = self._list_actions(plan_id)
        if actions and all(action.effect_type == "READ" for action in actions):
            return {
                "__target__": "action_execution",
                "__logical_target__": "action_execution",
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        action = next(
            (item for item in actions if item.status == ActionStatusV1.APPROVED.value),
            None,
        )
        if action is None:
            return {
                "__target__": "domain_reconcile",
                "__logical_target__": "domain_reconcile",
            }
        request = WriteExecutionPhaseRequest(run_id, action.id, action.version)
        result = self._execution_phase.preflight(request)
        if result.disposition is WriteExecutionDisposition.CLAIM_READY:
            return {
                "__target__": "action_execution",
                "__logical_target__": "action_execution",
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "PREFLIGHT_READY",
                    "run_id": run_id,
                    "action_id": action.id,
                    "action_version": action.version,
                    "attempt_id": result.attempt_id,
                    "approval_id": result.approval_id,
                    "claimed_action_version": result.claimed_action_version,
                },
            }
        return self._preflight_failure_patch(
            state=state,
            plan_id=plan_id,
            action_id=action.id,
            result=result,
        )

    def __call__(self, state: GraphState) -> GraphState:
        run_id = cast(str, state["run_id"])
        if self._should_stop_for_cancel(run_id):
            return self._cancelled_state(state=state, plan_id="", verification_statuses=[])
        plan_id = self._required_string(state.get("approved_plan_id"), "approved_plan_id")
        actions = self._list_actions(plan_id)
        if actions and all(action.effect_type == "READ" for action in actions):
            return self._execute_read_only_plan(state, plan_id, actions)

        verification_statuses: list[str] = []
        for action in actions:
            state_update = self._execute_action(
                state=state,
                run_id=run_id,
                plan_id=plan_id,
                action=action,
                verification_statuses=verification_statuses,
            )
            if state_update is not None:
                return state_update

        completion_ready = self._completion_is_ready(
            run_id=run_id,
            actions=actions,
            verification_statuses=verification_statuses,
        )
        if not completion_ready:
            return self._not_completable_state(
                state=state,
                plan_id=plan_id,
                actions=actions,
                verification_statuses=verification_statuses,
            )
        return {
            **state,
            "__target__": "response_synthesis",
            "__logical_target__": "response_synthesis",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "__workflow_control__": _workflow_control(
                "WRITE_RUN_COMPLETABLE",
                plan_id=plan_id,
                action_statuses=verification_statuses,
            ),
        }

    def _execute_action(
        self,
        *,
        state: GraphState,
        run_id: str,
        plan_id: str,
        action: ActionRecord,
        verification_statuses: list[str],
    ) -> GraphState | None:
        if self._should_stop_for_cancel(run_id):
            return self._cancelled_state(
                state=state,
                plan_id=plan_id,
                verification_statuses=verification_statuses,
            )
        control = state.get("__workflow_control__")
        control_matches = (
            isinstance(control, dict)
            and control.get("stage") == "PREFLIGHT_READY"
            and control.get("action_id") == action.id
        )
        if action.status in {
            ActionStatusV1.VERIFIED.value,
            ActionStatusV1.MISMATCH.value,
            ActionStatusV1.FAILED.value,
            ActionStatusV1.BLOCKED.value,
            ActionStatusV1.DEPENDENCY_BLOCKED.value,
            ActionStatusV1.CANCELLED.value,
            ActionStatusV1.REJECTED.value,
        }:
            verification_statuses.append(action.status)
            return None
        if action.status != ActionStatusV1.APPROVED.value and not control_matches:
            return None

        if not control_matches:
            return {
                **state,
                "__target__": "preflight",
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        assert isinstance(control, dict)
        phase_result = self._execution_phase.execute_claimed(
            WriteExecutionPhaseRequest(
                run_id,
                action.id,
                cast(int, control["action_version"]),
            ),
            WriteExecutionPhaseResult(
                disposition=WriteExecutionDisposition.CLAIM_READY,
                attempt_id=cast(str | None, control.get("attempt_id")),
                approval_id=cast(str | None, control.get("approval_id")),
                claimed_action_version=cast(int | None, control.get("claimed_action_version")),
            ),
        )
        state = cast(GraphState, {**state, "__workflow_control__": None})
        if phase_result.disposition is WriteExecutionDisposition.PREFLIGHT_REAPPROVAL_REQUIRED:
            _ = interrupt(
                {
                    "interrupt_kind": "APPROVAL",
                    "run_id": run_id,
                    "plan_id": plan_id,
                    "action_id": action.id,
                    "reason": "PREFLIGHT_REAPPROVAL_REQUIRED",
                }
            )
            return {
                **state,
                "__target__": "action_execution",
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        if phase_result.disposition is WriteExecutionDisposition.PREFLIGHT_BLOCKED:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "PREFLIGHT_BLOCKED",
                    "reason": "PREFLIGHT_BLOCKED",
                    "action_id": action.id,
                    "safe_error_code": phase_result.safe_error_code,
                },
            }
        if phase_result.disposition in {
            WriteExecutionDisposition.DOMAIN_RECONCILE,
            WriteExecutionDisposition.CLAIM_SKIPPED,
        }:
            return self._reconcile_phase_result(
                state=state,
                action_id=action.id,
                phase_result=phase_result,
            )
        if phase_result.disposition is WriteExecutionDisposition.CANCEL_REQUESTED:
            if phase_result.action_status is not None:
                verification_statuses.append(phase_result.action_status)
            return self._cancelled_state(
                state=state,
                plan_id=plan_id,
                verification_statuses=verification_statuses,
            )
        if phase_result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    result=phase_result,
                    routing_outcome="FAILED",
                ),
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "REAUTH_REQUIRED",
                    "reason": "REAUTH_REQUIRED",
                    "action_id": action.id,
                    "action_status": phase_result.action_status,
                    "result_code": phase_result.result_code,
                },
            }
        if phase_result.disposition is WriteExecutionDisposition.UNKNOWN_RESULT:
            return {
                **state,
                "__target__": "recovery",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    result=phase_result,
                    routing_outcome="UNKNOWN_RESULT",
                ),
                "__workflow_control__": _workflow_control(
                    phase_result.result_code or "UNKNOWN_RESULT",
                    safe_error_code=phase_result.safe_error_code,
                ),
            }
        if phase_result.disposition is WriteExecutionDisposition.EXECUTED:
            verification_statuses.append(ActionStatusV1.EXECUTED.value)
            return {
                **state,
                "__target__": "verification",
                "__logical_target__": "verification",
                "workflow_phase": WorkflowPhase.VERIFICATION.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    result=phase_result,
                    routing_outcome="EXECUTED",
                ),
                "verification_summary": None,
            }
        if phase_result.disposition is WriteExecutionDisposition.FAILED:
            verification_statuses.append(ActionStatusV1.FAILED.value)
            continue_execution = self._has_independent_executable_action(plan_id, action.id)
            return {
                **state,
                "__target__": "preflight" if continue_execution else "end",
                "__logical_target__": "preflight" if continue_execution else "end",
                "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    result=phase_result,
                    routing_outcome="FAILED",
                ),
                "__workflow_control__": _workflow_control(
                    (
                        "FAILED_CONTINUE_INDEPENDENT"
                        if continue_execution
                        else "FAILED_RETRY_OR_CANCEL_REQUIRED"
                    ),
                    action_id=action.id,
                    result_code=phase_result.result_code,
                    action_statuses=verification_statuses,
                ),
            }

        verification_statuses.append(
            self._required_string(phase_result.action_status, "action_status")
        )
        if self._should_stop_for_cancel(run_id):
            return self._cancelled_state(
                state=state,
                plan_id=plan_id,
                verification_statuses=verification_statuses,
            )
        return None

    def _preflight_failure_patch(
        self,
        *,
        state: Mapping[str, object],
        plan_id: str,
        action_id: str,
        result: WriteExecutionPhaseResult,
    ) -> dict[str, object]:
        if result.disposition is WriteExecutionDisposition.PREFLIGHT_REAPPROVAL_REQUIRED:
            _ = interrupt(
                {
                    "interrupt_kind": "APPROVAL",
                    "run_id": state["run_id"],
                    "plan_id": plan_id,
                    "action_id": action_id,
                    "reason": "PREFLIGHT_REAPPROVAL_REQUIRED",
                }
            )
            return {
                "__target__": "preflight",
                "__logical_target__": "preflight",
                "workflow_phase": WorkflowPhase.PREFLIGHT.value,
            }
        if result.disposition is WriteExecutionDisposition.PREFLIGHT_BLOCKED:
            return {
                "__target__": "end",
                "__logical_target__": "end",
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "PREFLIGHT_BLOCKED",
                    "reason": "PREFLIGHT_BLOCKED",
                    "action_id": action_id,
                    "safe_error_code": result.safe_error_code,
                },
            }
        if result.disposition is WriteExecutionDisposition.REAUTH_REQUIRED:
            return {
                "__target__": "end",
                "__logical_target__": "end",
                "__workflow_control__": {
                    "schema_version": 1,
                    "stage": "REAUTH_REQUIRED",
                    "reason": "REAUTH_REQUIRED",
                    "action_id": action_id,
                    "result_code": result.result_code,
                },
            }
        if result.disposition is WriteExecutionDisposition.CANCEL_REQUESTED:
            return {
                "__target__": "end",
                "__logical_target__": "end",
                "__workflow_control__": _workflow_control("CANCEL_REQUESTED", plan_id=plan_id),
            }
        return {
            "__target__": "domain_reconcile",
            "__logical_target__": "domain_reconcile",
        }

    def _reconcile_phase_result(
        self,
        *,
        state: GraphState,
        action_id: str,
        phase_result: object,
    ) -> GraphState:
        action_status = getattr(phase_result, "action_status", None)
        current_status = cast(str | None, getattr(phase_result, "current_status", None))
        next_allowed = tuple(
            str(item) for item in getattr(phase_result, "next_allowed_commands", ())
        )
        aggregate = (
            ReconcileAggregate.ACTION if action_status is not None else ReconcileAggregate.RUN
        )
        if aggregate is ReconcileAggregate.RUN and current_status is not None and not next_allowed:
            try:
                next_allowed = tuple(
                    item.value for item in next_allowed_run_commands(RunStatusV1(current_status))
                )
            except ValueError:
                next_allowed = ()
        decision = reconcile_write_conflict(
            aggregate=aggregate,
            current_status=current_status,
            next_allowed_commands=next_allowed,
        )
        return {
            **state,
            "__target__": decision.target,
            "workflow_phase": self._phase_for_reconcile_target(decision.target),
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "DOMAIN_RECONCILE",
                "reason": "DOMAIN_RECONCILE",
                "action_id": action_id,
                "aggregate": aggregate.value,
                "result_code": getattr(phase_result, "result_code", None),
                "current_status": current_status,
                "current_version": getattr(phase_result, "current_version", None),
                "next_allowed_commands": list(next_allowed),
                "reconcile_outcome": decision.outcome,
            },
        }

    def _not_completable_state(
        self,
        *,
        state: GraphState,
        plan_id: str,
        actions: tuple[ActionRecord, ...],
        verification_statuses: list[str],
    ) -> GraphState:
        statuses = {ActionStatusV1(action.status) for action in actions}
        if statuses & {
            ActionStatusV1.UNKNOWN_RESULT,
            ActionStatusV1.MISMATCH,
            ActionStatusV1.EXECUTED,
        }:
            target = "recovery"
            outcome = "RECOVERY_REQUIRED"
        elif statuses & {
            ActionStatusV1.PROPOSED,
            ActionStatusV1.MODIFIED,
            ActionStatusV1.EXPIRED,
        }:
            target = "waiting_approval"
            outcome = "WAITING_APPROVAL"
        else:
            target = "end"
            outcome = "SUSPEND_NOT_COMPLETABLE"
        return {
            **state,
            "__target__": target,
            "workflow_phase": self._phase_for_reconcile_target(target),
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "WRITE_RUN_NOT_COMPLETABLE",
                "reason": "WRITE_RUN_NOT_COMPLETABLE",
                "reconcile_outcome": outcome,
                "plan_id": plan_id,
                "action_statuses": verification_statuses,
            },
        }

    def _completion_is_ready(
        self,
        *,
        run_id: str,
        actions: tuple[ActionRecord, ...],
        verification_statuses: list[str],
    ) -> bool:
        return bool(
            actions
            and len(verification_statuses) == len(actions)
            and all(status == ActionStatusV1.VERIFIED.value for status in verification_statuses)
            and not self._has_persisted_cancel_intent(run_id)
        )

    @staticmethod
    def _phase_for_reconcile_target(target: str) -> str:
        if target == "recovery":
            return WorkflowPhase.RECOVERY.value
        if target == "waiting_approval":
            return WorkflowPhase.PREFLIGHT.value
        return WorkflowPhase.ACTION_EXECUTION.value

    @staticmethod
    def _cancelled_state(
        *,
        state: GraphState,
        plan_id: str,
        verification_statuses: list[str],
    ) -> GraphState:
        return {
            **state,
            "__target__": "cancel_resolution",
            "__logical_target__": "cancel_resolution",
            "workflow_phase": "CANCEL_RESOLUTION",
            "__workflow_control__": _workflow_control(
                "CANCEL_REQUESTED",
                plan_id=plan_id,
                action_statuses=verification_statuses,
            ),
        }

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value


def _workflow_control(reason: str, **details: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "WRITE_EXECUTION",
        "reason": reason,
        **details,
    }


def _execution_summary(
    *,
    action_id: str,
    result: WriteExecutionPhaseResult,
    routing_outcome: str,
) -> ExecutionSummaryV1:
    attempt_id = result.attempt_id
    source_action_version = result.current_version
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("Domain-backed execution summary requires execution_attempt_id")
    if not isinstance(source_action_version, int):
        raise ValueError("Domain-backed execution summary requires source_action_version")
    delivery_certainty = result.delivery_certainty
    if routing_outcome == "FAILED" and delivery_certainty is None:
        delivery_certainty = "NOT_SENT"
    return cast(
        ExecutionSummaryV1,
        {
            "schema_version": 1,
            "action_id": action_id,
            "execution_attempt_id": attempt_id,
            "routing_outcome": routing_outcome,
            "delivery_certainty": delivery_certainty,
            "source_action_version": source_action_version,
        },
    )
