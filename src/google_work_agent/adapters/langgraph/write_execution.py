"""LangGraph translation for approved action execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.execution_phase import (
    WriteExecutionDisposition,
    WriteExecutionPhaseCoordinator,
    WriteExecutionPhaseRequest,
)
from google_work_agent.application.run_terminal import (
    CompleteWriteRunCommand,
    CompleteWriteRunService,
)
from google_work_agent.application.workflows.contracts import WorkflowPhase
from google_work_agent.domain import ActionStatus
from google_work_agent.ports import ActionRecord


class WriteExecutionNode:
    """Translate one approved Plan execution into LangGraph state updates."""

    def __init__(
        self,
        *,
        id_factory: Callable[[], str],
        request_hash: Callable[[dict[str, object]], str],
        should_stop_for_cancel: Callable[[str], bool],
        list_actions: Callable[[str], tuple[ActionRecord, ...]],
        execute_read_only_plan: Callable[[GraphState, str, tuple[ActionRecord, ...]], GraphState],
        execution_phase: WriteExecutionPhaseCoordinator,
        has_persisted_cancel_intent: Callable[[str], bool],
        complete_write_run: CompleteWriteRunService,
        current_run_version: Callable[[str], int],
    ) -> None:
        self._id_factory = id_factory
        self._request_hash = request_hash
        self._should_stop_for_cancel = should_stop_for_cancel
        self._list_actions = list_actions
        self._execute_read_only_plan = execute_read_only_plan
        self._execution_phase = execution_phase
        self._has_persisted_cancel_intent = has_persisted_cancel_intent
        self._complete_write_run = complete_write_run
        self._current_run_version = current_run_version

    def __call__(self, state: GraphState) -> GraphState:
        run_id = cast(str, state["run_id"])
        if self._should_stop_for_cancel(run_id):
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
                "execution_summary": {"result": "CANCEL_REQUESTED"},
            }
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
        self._complete_if_verified(
            run_id=run_id,
            actions=actions,
            verification_statuses=verification_statuses,
        )
        return {
            **state,
            "__target__": "finalize",
            "workflow_phase": WorkflowPhase.VERIFICATION.value,
            "execution_summary": {"result": "EXECUTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
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
        if action.status in {
            ActionStatus.VERIFIED.value,
            ActionStatus.MISMATCH.value,
            ActionStatus.FAILED.value,
            ActionStatus.BLOCKED.value,
            ActionStatus.DEPENDENCY_BLOCKED.value,
        }:
            verification_statuses.append(action.status)
            return None
        if action.status != ActionStatus.APPROVED.value:
            return None

        phase_result = self._execution_phase.execute(
            WriteExecutionPhaseRequest(
                run_id=run_id,
                action_id=action.id,
                action_version=action.version,
            )
        )
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
                "execution_summary": {
                    "result": "PREFLIGHT_BLOCKED",
                    "action_id": action.id,
                    "safe_error_code": phase_result.safe_error_code,
                },
            }
        if phase_result.disposition is WriteExecutionDisposition.CLAIM_SKIPPED:
            return None
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
                "execution_summary": {"result": "REAUTH_REQUIRED", "action_id": action.id},
            }
        if phase_result.disposition is WriteExecutionDisposition.UNKNOWN_RESULT:
            return {
                **state,
                "__target__": "recovery",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
                "execution_summary": {
                    "result": phase_result.result_code,
                    "action_id": action.id,
                    "safe_error_code": phase_result.safe_error_code,
                },
            }
        if phase_result.disposition is WriteExecutionDisposition.FAILED:
            verification_statuses.append(ActionStatus.FAILED.value)
            return None

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

    def _complete_if_verified(
        self,
        *,
        run_id: str,
        actions: tuple[ActionRecord, ...],
        verification_statuses: list[str],
    ) -> None:
        if (
            not actions
            or not verification_statuses
            or not all(status == ActionStatus.VERIFIED.value for status in verification_statuses)
            or self._has_persisted_cancel_intent(run_id)
        ):
            return
        self._complete_write_run(
            CompleteWriteRunCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash({"kind": "complete_write_run", "run_id": run_id}),
                run_id=run_id,
                expected_version=self._current_run_version(run_id),
            )
        )

    @staticmethod
    def _cancelled_state(
        *,
        state: GraphState,
        plan_id: str,
        verification_statuses: list[str],
    ) -> GraphState:
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
            "execution_summary": {"result": "CANCEL_REQUESTED", "plan_id": plan_id},
            "verification_summary": {"action_statuses": verification_statuses},
        }

    @staticmethod
    def _required_string(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field_name} is required")
        return value
