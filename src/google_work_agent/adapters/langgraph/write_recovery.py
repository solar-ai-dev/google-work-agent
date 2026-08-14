"""LangGraph orchestration for write recovery and restart verification."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.execution_phase import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionPhaseCoordinator,
)
from google_work_agent.application.workflows.contracts import WorkflowPhase
from google_work_agent.domain import ActionStatus, ResultCode
from google_work_agent.ports import ActionRecord, PlanRecord


class WriteRecoveryCoordinator:
    """Coordinate UNKNOWN_RESULT recovery and verification after restart."""

    def __init__(
        self,
        *,
        latest_unknown_action: Callable[[str], tuple[ActionRecord, str, int] | None],
        execution_phase: WriteExecutionPhaseCoordinator,
        complete_write_run_if_verified: Callable[[str, str], None],
        plans_for_run: Callable[[str], tuple[PlanRecord, ...]],
        list_actions: Callable[[str], tuple[ActionRecord, ...]],
        begin_verification: Callable[[str], None],
        latest_attempt_id: Callable[[str], str],
    ) -> None:
        self._latest_unknown_action = latest_unknown_action
        self._execution_phase = execution_phase
        self._complete_write_run_if_verified = complete_write_run_if_verified
        self._plans_for_run = plans_for_run
        self._list_actions = list_actions
        self._begin_verification = begin_verification
        self._latest_attempt_id = latest_attempt_id

    def recover_unknown(self, state: GraphState) -> GraphState:
        unknown_action = self._latest_unknown_action(cast(str, state["run_id"]))
        if unknown_action is None:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
            }
        action, attempt_id, attempt_version = unknown_action
        response = self._execution_phase.recover_unknown(
            UnknownRecoveryPhaseRequest(
                action_id=action.id,
                effect_type=action.effect_type,
                action_version=action.version,
                attempt_id=attempt_id,
                attempt_version=attempt_version,
            )
        )
        if response.applied and response.action_status == ActionStatus.VERIFIED.value:
            self._complete_write_run_if_verified(action.plan_id, cast(str, state["run_id"]))
        outcome = (
            "RECOVERY_REQUIRED"
            if response.result_code == ResultCode.RECOVERY_REQUIRED.value
            else "RECOVERED"
        )
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": outcome, "action_id": action.id},
            "verification_summary": {"action_statuses": [response.action_status]},
        }

    def recover_executed(self, state: GraphState, run_id: str) -> GraphState:
        plans = self._plans_for_run(run_id)
        if not plans:
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
            }
        latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
        statuses: list[str] = []
        verification_started = False
        for action in self._list_actions(latest_plan.id):
            if action.status != ActionStatus.EXECUTED.value:
                statuses.append(action.status)
                continue
            if not verification_started:
                self._begin_verification(run_id)
                verification_started = True
            verified = self._execution_phase.verify_executed(
                action_id=action.id,
                action_version=action.version,
                attempt_id=self._latest_attempt_id(action.id),
                request_kind="verify_after_restart",
            )
            statuses.append(verified.action_status)
        self._complete_write_run_if_verified(latest_plan.id, run_id)
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": "RESTART_RECONCILED", "plan_id": latest_plan.id},
            "verification_summary": {"action_statuses": statuses},
        }
