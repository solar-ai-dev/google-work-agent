"""LangGraph orchestration for write recovery and restart verification."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from google_work_agent.adapters.langgraph.main.state import (
    ExecutionSummaryV1,
    GraphState,
    VerificationSummaryV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.write_execution_driver import (
    UnknownRecoveryPhaseRequest,
    WriteExecutionDisposition,
    WriteExecutionPhaseRequest,
    WriteExecutionStructuralDriver,
)
from google_work_agent.adapters.langgraph.write_reconciliation import (
    ReconcileAggregate,
    reconcile_write_conflict,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.application.use_cases.run.begin_verification import BeginVerificationResult
from google_work_agent.application.use_cases.run.run_terminal import RunTransitionResponse
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult
from google_work_agent.domain.run.model import RunCommand, RunStatusV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceGatewayError,
)


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
        execution_phase: WriteExecutionStructuralDriver,
        write_run_completion_ready: Callable[[str, str], bool],
        plans_for_run: Callable[[str], tuple[PlanRecord, ...]],
        list_actions: Callable[[str], tuple[ActionRecord, ...]],
        begin_verification: Callable[[str, str, str], BeginVerificationResult | None],
        latest_attempt_id: Callable[[str], str],
    ) -> None:
        self._latest_unknown_action = latest_unknown_action
        self._execution_phase = execution_phase
        self._write_run_completion_ready = write_run_completion_ready
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
        if response.action_status == ActionStatusV1.EXECUTED.value:
            return {
                **state,
                "__target__": "verification",
                "__logical_target__": "verification",
                "workflow_phase": WorkflowPhase.VERIFICATION.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    attempt_id=response.attempt_id or attempt_id,
                    source_action_version=response.action_version,
                ),
                "verification_summary": None,
            }
        if response.action_status != ActionStatusV1.VERIFIED.value:
            return self._suspend_action_response(
                state=state,
                action_id=action.id,
                response=response,
                outcome="RECOVERY_NOT_VERIFIED",
            )

        if self._write_run_completion_ready(action.plan_id, run_id):
            return {
                **state,
                "__target__": "response_synthesis",
                "__logical_target__": "response_synthesis",
                "workflow_phase": WorkflowPhase.RECOVERY.value,
                "execution_summary": _execution_summary(
                    action_id=action.id,
                    attempt_id=response.attempt_id or attempt_id,
                    source_action_version=response.action_version,
                ),
                "verification_summary": _verification_summary(response),
            }

        # The recovered action is verified but other actions can still be
        # pending. Re-enter normal action execution; this does not replay the
        # recovery command and the verified action is skipped deterministically.
        return {
            **state,
            "__target__": "action_execution",
            "workflow_phase": WorkflowPhase.ACTION_EXECUTION.value,
            "execution_summary": _execution_summary(
                action_id=action.id,
                attempt_id=response.attempt_id or attempt_id,
                source_action_version=response.action_version,
            ),
            "verification_summary": _verification_summary(response),
            "__workflow_control__": _workflow_control("RECOVERED_ACTION"),
        }

    def recover_executed(self, state: GraphState, run_id: str) -> GraphState:
        plans = tuple(
            plan
            for plan in self._plans_for_run(run_id)
            if plan.status is not PlanStatusV1.SUPERSEDED
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
            if action.status != ActionStatusV1.EXECUTED.value:
                statuses.append(action.status)
                continue

            if not verification_started:
                attempt_id = self._latest_attempt_id(action.id)
                begin = self._begin_verification(run_id, action.id, attempt_id)
                if begin is not None and not begin.applied:
                    return self._reconcile_run_command_result(
                        state=state,
                        result=begin,
                        source="BEGIN_VERIFICATION",
                        verification_statuses=statuses,
                    )
                verification_started = True

            try:
                verified = self._execution_phase.verify_executed(
                    action_id=action.id,
                    action_version=action.version,
                    attempt_id=attempt_id,
                    request_kind="verify_after_restart",
                )
            except GoogleWorkspaceGatewayError as error:
                failure = self._execution_phase.handle_verification_error(
                    request=WriteExecutionPhaseRequest(run_id, action.id, action.version),
                    error=error,
                )
                if failure.disposition is not WriteExecutionDisposition.REAUTH_REQUIRED:
                    return self._suspend(
                        state=state,
                        outcome="DOMAIN_RECONCILE",
                        facts={"action_id": action.id, "result_code": failure.result_code},
                        verification_statuses=statuses,
                    )
                return {
                    **state,
                    "__target__": "end",
                    "workflow_phase": WorkflowPhase.VERIFICATION.value,
                    "__workflow_control__": {
                        "schema_version": 1,
                        "stage": "REAUTH_REQUIRED",
                        "reason": "REAUTH_REQUIRED",
                        "action_id": action.id,
                        "safe_error_code": failure.safe_error_code,
                    },
                }
            if not verified.applied:
                return self._suspend_action_response(
                    state=state,
                    action_id=action.id,
                    response=verified,
                    outcome="DOMAIN_RECONCILE",
                    verification_statuses=statuses,
                )
            statuses.append(verified.action_status)
            state = cast(
                GraphState,
                {
                    **state,
                    "execution_summary": _execution_summary(
                        action_id=action.id,
                        attempt_id=verified.attempt_id or attempt_id,
                        source_action_version=verified.action_version,
                    ),
                    "verification_summary": _verification_summary(verified),
                },
            )

        if not self._write_run_completion_ready(latest_plan.id, run_id):
            if any(
                status in {ActionStatusV1.APPROVED.value, ActionStatusV1.PROPOSED.value}
                for status in statuses
            ):
                return {
                    **state,
                    "__target__": "preflight",
                    "__logical_target__": "preflight",
                    "workflow_phase": WorkflowPhase.PREFLIGHT.value,
                    "__workflow_control__": _workflow_control(
                        "VERIFICATION_COMPLETE_NEXT_ACTION",
                        plan_id=latest_plan.id,
                        action_statuses=statuses,
                    ),
                }
            return self._suspend(
                state=state,
                outcome="RECOVERY_NOT_COMPLETABLE",
                facts={"plan_id": latest_plan.id, "action_statuses": statuses},
                verification_statuses=statuses,
            )
        return {
            **state,
            "__target__": "response_synthesis",
            "__logical_target__": "response_synthesis",
            "workflow_phase": WorkflowPhase.RECOVERY.value,
            "__workflow_control__": _workflow_control(
                "RESTART_RECONCILED",
                plan_id=latest_plan.id,
                action_statuses=statuses,
            ),
        }

    def _suspend_action_response(
        self,
        *,
        state: GraphState,
        action_id: str,
        response: WriteActionResponse,
        outcome: str,
        verification_statuses: list[str] | None = None,
    ) -> GraphState:
        action_status = str(response.action_status)
        action_version = int(response.action_version)
        next_allowed = tuple(str(item) for item in response.next_allowed_commands)
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
        result: CommandResult[RunStatusV1, RunCommand] | BeginVerificationResult,
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
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "DOMAIN_RECONCILE",
                "reason": "DOMAIN_RECONCILE",
                "source": source,
                "result_code": result.result_code.value,
                "current_status": result.current_status.value,
                "current_version": result.current_version,
                "next_allowed_commands": list(next_allowed),
                "reconcile_destination": decision.target,
                "reconcile_outcome": decision.outcome,
                "verification_statuses": verification_statuses,
            },
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
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "DOMAIN_RECONCILE",
                "reason": "DOMAIN_RECONCILE",
                "source": source,
                "result_code": response.result_code,
                "current_status": response.run_status,
                "current_version": response.run_version,
                "next_allowed_commands": list(response.next_allowed_commands),
                "reconcile_destination": decision.target,
                "reconcile_outcome": decision.outcome,
                "verification_statuses": verification_statuses or [],
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
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "RECOVERY_SUSPENDED",
                "reason": outcome,
                **facts,
                "verification_statuses": verification_statuses or [],
            },
        }


def _workflow_control(reason: str, **details: object) -> dict[str, object]:
    return {
        "schema_version": 1,
        "stage": "WRITE_RECOVERY",
        "reason": reason,
        **details,
    }


def _execution_summary(
    *, action_id: str, attempt_id: str, source_action_version: int
) -> ExecutionSummaryV1:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "execution_attempt_id": attempt_id,
        "routing_outcome": "EXECUTED",
        "delivery_certainty": None,
        "source_action_version": source_action_version,
    }


def _verification_summary(response: WriteActionResponse) -> VerificationSummaryV1:
    verification_id = response.verification_id
    if not isinstance(verification_id, str) or not verification_id:
        raise ValueError("Domain-backed verification summary requires verification_id")
    if response.action_status not in {
        ActionStatusV1.VERIFIED.value,
        ActionStatusV1.MISMATCH.value,
    }:
        raise ValueError("verification summary requires VERIFIED or MISMATCH status")
    return cast(
        VerificationSummaryV1,
        {
            "schema_version": 1,
            "action_id": response.action_id,
            "verification_id": verification_id,
            "routing_outcome": response.action_status,
            "source_action_version": response.action_version,
        },
    )
