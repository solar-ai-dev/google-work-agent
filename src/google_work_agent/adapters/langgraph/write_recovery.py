"""LangGraph orchestration for write recovery and restart verification."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.write_reconciliation import (
    ReconcileAggregate,
    reconcile_write_conflict,
)
from google_work_agent.application.execution_phase import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionPhaseCoordinator,
)
from google_work_agent.application.run_terminal import RunTransitionResponse
from google_work_agent.application.orchestration.contracts import WorkflowPhase
from google_work_agent.domain import (
    ActionStatus,
    CommandResult,
    RunCommand,
    RunStatus,
)
from google_work_agent.ports import ActionRecord, PlanRecord, PlanStatus


class WriteRecoveryCoordinator:
    """Coordinate UNKNOWN_RESULT recovery and verification after restart.

    Every mutating command result is consumed. A non-applied result never
    falls through to another verification/completion mutation and recovery
    work is never automatically replayed from inside the recovery node.
    """

    def __init__(
        self,
        *,
        latest_unknown_action: Callable[[str], tuple[ActionRecord, str, int] | None],
        execution_phase: WriteExecutionPhaseCoordinator,
        complete_write_run_if_verified: Callable[[str, str], RunTransitionResponse | None],
        plans_for_run: Callable[[str], tuple[PlanRecord, ...]],
        list_actions: Callable[[str], tuple[ActionRecord, ...]],
        begin_verification: Callable[
            [str], CommandResult[RunStatus, RunCommand] | None
        ],
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
        run_id = cast(str, state["run_id"])
        unknown_action = self._latest_unknown_action(run_id)
        if unknown_action is None:
            return self.recover_executed(state, run_id)

        action, attempt_id, attempt_version = unknown_action
        response = self._execution_phase.recover_unknown(
            UnknownRecoveryPhaseRequest(
                run_id=run_id,
                action_id=action.id,
                effect_type=action.effect_type,
                action_version=action.version,
                attempt_id=attempt_id,
                attempt_version=attempt_version,
            )
        )

        if response.safe_error_code in {"AUTH_EXPIRED", "PERMISSION_DENIED"}:
            return self._suspend_action_response(
                state=state,
                action_id=action.id,
                response=response,
                outcome="REAUTH_REQUIRED",
            )
        if not response.applied:
            return self._suspend_action_response(
                state=state,
                action_id=action.id,
                response=response,
                outcome="DOMAIN_RECONCILE",
            )
        if response.action_status != ActionStatus.VERIFIED.value:
            return self._suspend_action_response(
                state=state,
                action_id=action.id,
                response=response,
                outcome="RECOVERY_NOT_VERIFIED",
            )

        completion = self._complete_write_run_if_verified(action.plan_id, run_id)
        if completion is not None:
            if not completion.applied:
                return self._reconcile_run_response(
                    state=state,
                    response=completion,
                    source="RECOVERY_COMPLETE_WRITE_RUN",
                )
            return {
                **state,
                "__target__": "end",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
                "execution_summary": {
                    "result": "RECOVERED",
                    "action_id": action.id,
                    "run_status": completion.run_status,
                    "run_version": completion.run_version,
                },
                "verification_summary": {"action_statuses": [response.action_status]},
            }

        # The recovered action is verified but other actions can still be
        # pending. Re-enter normal action execution; this does not replay the
        # recovery command and the verified action is skipped deterministically.
        return {
            **state,
            "__target__": "action_execution",
            "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
            "execution_summary": {"result": "RECOVERED_ACTION", "action_id": action.id},
            "verification_summary": {"action_statuses": [response.action_status]},
        }

    def recover_executed(self, state: GraphState, run_id: str) -> GraphState:
        plans = tuple(
            plan for plan in self._plans_for_run(run_id) if plan.status is not PlanStatus.SUPERSEDED
        )
        if not plans:
            return self._suspend(
                state=state,
                outcome="RECOVERY_PLAN_MISSING",
                facts={"run_id": run_id},
            )
        latest_plan = sorted(plans, key=lambda item: (item.revision_no, item.created_at_ms))[-1]
        statuses: list[str] = []
        verification_started = False

        for action in self._list_actions(latest_plan.id):
            if action.status != ActionStatus.EXECUTED.value:
                statuses.append(action.status)
                continue

            if not verification_started:
                begin = self._begin_verification(run_id)
                if begin is not None and not begin.applied:
                    return self._reconcile_run_command_result(
                        state=state,
                        result=begin,
                        source="BEGIN_VERIFICATION",
                        verification_statuses=statuses,
                    )
                verification_started = True

            verified = self._execution_phase.verify_executed(
                action_id=action.id,
                action_version=action.version,
                attempt_id=self._latest_attempt_id(action.id),
                request_kind="verify_after_restart",
            )
            if not verified.applied:
                return self._suspend_action_response(
                    state=state,
                    action_id=action.id,
                    response=verified,
                    outcome="DOMAIN_RECONCILE",
                    verification_statuses=statuses,
                )
            statuses.append(verified.action_status)

        completion = self._complete_write_run_if_verified(latest_plan.id, run_id)
        if completion is None:
            return self._suspend(
                state=state,
                outcome="RECOVERY_NOT_COMPLETABLE",
                facts={"plan_id": latest_plan.id, "action_statuses": statuses},
                verification_statuses=statuses,
            )
        if not completion.applied:
            return self._reconcile_run_response(
                state=state,
                response=completion,
                source="COMPLETE_WRITE_RUN",
                verification_statuses=statuses,
            )
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {
                "result": "RESTART_RECONCILED",
                "plan_id": latest_plan.id,
                "run_status": completion.run_status,
                "run_version": completion.run_version,
            },
            "verification_summary": {"action_statuses": statuses},
        }

    def _suspend_action_response(
        self,
        *,
        state: GraphState,
        action_id: str,
        response: object,
        outcome: str,
        verification_statuses: list[str] | None = None,
    ) -> GraphState:
        action_status = str(getattr(response, "action_status"))
        action_version = int(getattr(response, "action_version"))
        next_allowed = tuple(str(item) for item in getattr(response, "next_allowed_commands"))
        decision = reconcile_write_conflict(
            aggregate=ReconcileAggregate.ACTION,
            current_status=action_status,
            next_allowed_commands=next_allowed,
        )
        # We are already inside the recovery destination. Routing directly
        # back to recovery would automatically issue a fresh recovery command
        # in the same invocation, which is forbidden. Suspend instead while
        # preserving the deterministic destination as a reconciliation fact.
        return self._suspend(
            state=state,
            outcome=outcome,
            facts={
                "action_id": action_id,
                "result_code": getattr(response, "result_code", None),
                "current_status": action_status,
                "current_version": action_version,
                "next_allowed_commands": list(next_allowed),
                "reconcile_destination": decision.target,
                "reconcile_outcome": decision.outcome,
                "safe_error_code": getattr(response, "safe_error_code", None),
            },
            verification_statuses=verification_statuses,
        )

    def _reconcile_run_command_result(
        self,
        *,
        state: GraphState,
        result: CommandResult[RunStatus, RunCommand],
        source: str,
        verification_statuses: list[str],
    ) -> GraphState:
        next_allowed = tuple(item.value for item in result.next_allowed_commands)
        decision = reconcile_write_conflict(
            aggregate=ReconcileAggregate.RUN,
            current_status=result.current_status.value,
            next_allowed_commands=next_allowed,
        )
        target = decision.target
        if target == "recovery":
            # Already at the recovery boundary; do not self-loop and retry.
            target = "end"
        return {
            **state,
            "__target__": target,
            "workflow_phase": (
                WorkflowPhase.RECOVERY.value
                if target == "end" or target == "recovery"
                else WorkflowPhase.PREFLIGHT.value
            ),
            "execution_summary": {
                "result": "DOMAIN_RECONCILE",
                "source": source,
                "result_code": result.result_code.value,
                "current_status": result.current_status.value,
                "current_version": result.current_version,
                "next_allowed_commands": list(next_allowed),
                "reconcile_destination": decision.target,
                "reconcile_outcome": decision.outcome,
            },
            "verification_summary": {"action_statuses": verification_statuses},
        }

    def _reconcile_run_response(
        self,
        *,
        state: GraphState,
        response: RunTransitionResponse,
        source: str,
        verification_statuses: list[str] | None = None,
    ) -> GraphState:
        decision = reconcile_write_conflict(
            aggregate=ReconcileAggregate.RUN,
            current_status=response.run_status,
            next_allowed_commands=response.next_allowed_commands,
        )
        target = decision.target
        if target == "recovery":
            target = "end"
        return {
            **state,
            "__target__": target,
            "workflow_phase": (
                WorkflowPhase.RECOVERY.value
                if target == "end" or target == "recovery"
                else WorkflowPhase.PREFLIGHT.value
            ),
            "execution_summary": {
                "result": "DOMAIN_RECONCILE",
                "source": source,
                "result_code": response.result_code,
                "current_status": response.run_status,
                "current_version": response.run_version,
                "next_allowed_commands": list(response.next_allowed_commands),
                "reconcile_destination": decision.target,
                "reconcile_outcome": decision.outcome,
            },
            "verification_summary": {
                "action_statuses": verification_statuses or []
            },
        }

    @staticmethod
    def _suspend(
        *,
        state: GraphState,
        outcome: str,
        facts: dict[str, object],
        verification_statuses: list[str] | None = None,
    ) -> GraphState:
        return {
            **state,
            "__target__": "end",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "execution_summary": {"result": outcome, **facts},
            "verification_summary": {
                "action_statuses": verification_statuses or []
            },
        }
