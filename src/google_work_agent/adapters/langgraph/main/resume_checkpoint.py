"""Checkpoint projection and runtime verification for Application-owned Run resume."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.application.orchestration.contracts import (
    WorkflowPhase,
)
from google_work_agent.application.orchestration.supervisor import SupervisorTarget
from google_work_agent.domain import RunStatus
from google_work_agent.ports import WorkflowInvocationResult, WorkflowOutcome, WorkflowResumeRequest
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


class ResumeCheckpointMixin:
    """Expose persisted resume targets and continue only Handler-decided resumes."""

    def resolve_resume_authority(
        self, *, run_id: str, workflow_key: str, resume_kind: str
    ) -> dict[str, object] | None:
        """Read checkpoint authority without mutating Domain or workflow state."""
        snapshot = self._graph.get_state(
            self._config_for_thread(workflow_key),
            subgraphs=True,
        )
        if not snapshot.values and not snapshot.next:
            return None
        state = cast(GraphState, snapshot.values)
        if resume_kind == "CONFIRMATION":
            return self.resolve_pending_confirmation(run_id)
        if resume_kind == "REAUTH_COMPLETED":
            status = _reauth_resume_status(state)
            if status is None:
                return None
            authority: dict[str, object] = {"resume_status": status}
            continuation_target = self._reauth_continuation_target(state)
            if continuation_target is not None:
                authority["continuation_target"] = continuation_target
            return authority
        if resume_kind == "RECOVERY_RECHECK":
            return {"resume_status": RunStatus.VERIFYING.value}
        return None

    def resolve_resume_domain_status(
        self, *, run_id: str, workflow_key: str, resume_kind: str
    ) -> str | None:
        authority = self.resolve_resume_authority(
            run_id=run_id, workflow_key=workflow_key, resume_kind=resume_kind
        )
        status = None if authority is None else authority.get("resume_status")
        return status if isinstance(status, str) else None

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        if request.resume_kind == "REAUTH_COMPLETED":
            return self._resume_after_reauth_transition(request)
        return super().resume(request)

    def _resume_after_reauth_transition(
        self, request: WorkflowResumeRequest
    ) -> WorkflowInvocationResult:
        """Validate the persisted target and continue it without recovery semantics."""
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                request.run_id, request.workflow_key, WorkflowOutcome.CHECKPOINT_MISSING, {}
            )
        state = cast(GraphState, snapshot.values)
        if not self._is_profile_compatible(state):
            return WorkflowInvocationResult(
                request.run_id,
                request.workflow_key,
                WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                {"reason": "graph profile does not match persisted checkpoint"},
            )

        authority = self.resolve_resume_authority(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            resume_kind="REAUTH_COMPLETED",
        )
        expected_status = None if authority is None else authority.get("resume_status")
        expected_target = None if authority is None else authority.get("continuation_target")
        requested_target = request.resume_payload.get("continuation_target")
        if (
            not isinstance(expected_status, str)
            or self._current_run_status(request.run_id) != expected_status
        ):
            return WorkflowInvocationResult(
                request.run_id,
                request.workflow_key,
                WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                {"reason": "persisted Run status does not match reauth checkpoint authority"},
            )
        if (
            not isinstance(expected_target, str)
            or not expected_target
            or requested_target != expected_target
        ):
            return WorkflowInvocationResult(
                request.run_id,
                request.workflow_key,
                WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                {"reason": "reauth continuation target does not match persisted checkpoint"},
            )

        if snapshot.next:
            if expected_target not in snapshot.next:
                return WorkflowInvocationResult(
                    request.run_id,
                    request.workflow_key,
                    WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
                    {"reason": "pending checkpoint task does not match reauth continuation target"},
                )
            self._graph.invoke(None, config=config)
        else:
            self._graph.update_state(
                config,
                {"__target__": expected_target},
                as_node=expected_target,
            )
            self._graph.invoke(None, config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def _reauth_continuation_target(self, state: GraphState) -> str | None:
        phase = state.get("workflow_phase")
        if not isinstance(phase, str):
            return None
        if phase == WorkflowPhase.REQUEST_ANALYSIS.value:
            return self._topology[0]
        target_by_phase = {
            WorkflowPhase.TOOL_ROUTING.value: SupervisorTarget.TOOL_ROUTE,
            WorkflowPhase.SOURCE_PLANNING.value: SupervisorTarget.SOURCE_PLANNING,
            WorkflowPhase.API_ACQUISITION.value: SupervisorTarget.API_ACQUISITION,
            WorkflowPhase.CONTEXT_RETRIEVAL.value: SupervisorTarget.CONTEXT_RETRIEVAL,
            WorkflowPhase.CONTEXT_EVALUATION.value: SupervisorTarget.CONTEXT_RETRIEVAL,
            WorkflowPhase.WORK_ANALYSIS.value: SupervisorTarget.WORK_ANALYSIS,
            WorkflowPhase.SOLUTION_PLANNING.value: SupervisorTarget.SOLUTION_PLANNING,
            WorkflowPhase.PLAN_REVIEW.value: SupervisorTarget.PLAN_REVIEW_INSPECT,
            WorkflowPhase.DOMAIN_VALIDATION.value: SupervisorTarget.DOMAIN_VALIDATION,
            WorkflowPhase.WAITING_APPROVAL.value: SupervisorTarget.WAITING_APPROVAL,
            WorkflowPhase.PREFLIGHT.value: SupervisorTarget.ACTION_EXECUTION,
            WorkflowPhase.ACTION_EXECUTION.value: SupervisorTarget.ACTION_EXECUTION,
            WorkflowPhase.VERIFICATION.value: SupervisorTarget.ACTION_EXECUTION,
        }
        target = target_by_phase.get(phase)
        if target is None:
            return None
        return self._route_translator.translate(target.value).node

    def resolve_pending_confirmation(self, run_id: str) -> dict[str, object] | None:
        with self._unit_of_work_factory() as unit_of_work:
            binding = unit_of_work.checkpoints.load_workflow_binding(run_id)
        if binding is None:
            return None
        snapshot = self._graph.get_state(
            self._config_for_thread(binding.workflow_key), subgraphs=True
        )
        latest = self._checkpoint_port.load_same_run_checkpoint(run_id, binding.langgraph_thread_id)
        if latest is None or latest.registered_resume_target is None:
            return None
        for value in _pending_interrupt_values(snapshot):
            if value.get("interrupt_kind") != "CONFIRMATION":
                continue
            raw_target = value.get("resume_target")
            if not isinstance(raw_target, Mapping):
                return None
            try:
                target = AgentNodeResumeTargetV2(**dict(raw_target))  # type: ignore[arg-type]
                self._resume_target_registry.validate(target)
            except (TypeError, ValueError):
                return None
            if target != latest.registered_resume_target:
                return None
            raw_options = value.get("options", [])
            if not isinstance(raw_options, list):
                return None
            options = [
                str(option["option_id"])
                for option in raw_options
                if isinstance(option, Mapping)
                and isinstance(option.get("option_id"), str)
                and option["option_id"]
            ]
            return {
                "interrupt_id": value.get("interrupt_id"),
                "semantic_owner_id": value.get("semantic_owner_id"),
                "resume_target": dict(raw_target),
                "pre_confirmation_status": value.get("pre_confirmation_status"),
                "question": value.get("question"),
                "options": options,
                "checkpoint_id": latest.checkpoint_id,
                "checkpoint_generation": latest.checkpoint_generation,
                "policy_confirmation": value.get("policy_confirmation"),
            }
        return None


def _pending_interrupt_values(snapshot: object) -> list[Mapping[str, object]]:
    values: list[Mapping[str, object]] = []
    for pending in getattr(snapshot, "interrupts", ()):
        value = getattr(pending, "value", None)
        if isinstance(value, Mapping):
            values.append(value)
    for task in getattr(snapshot, "tasks", ()):
        for pending in getattr(task, "interrupts", ()):
            value = getattr(pending, "value", None)
            if isinstance(value, Mapping):
                values.append(value)
        state = getattr(task, "state", None)
        if state is not None and state is not snapshot:
            values.extend(_pending_interrupt_values(state))
    return values


def _reauth_resume_status(state: GraphState) -> str | None:
    phase = state.get("workflow_phase")
    if not isinstance(phase, str):
        return None
    mapping = {
        WorkflowPhase.REQUEST_ANALYSIS.value: RunStatus.ANALYZING,
        WorkflowPhase.TOOL_ROUTING.value: RunStatus.ANALYZING,
        WorkflowPhase.WORK_ANALYSIS.value: RunStatus.ANALYZING,
        WorkflowPhase.SOURCE_PLANNING.value: RunStatus.RETRIEVING,
        WorkflowPhase.API_ACQUISITION.value: RunStatus.RETRIEVING,
        WorkflowPhase.CONTEXT_RETRIEVAL.value: RunStatus.RETRIEVING,
        WorkflowPhase.CONTEXT_EVALUATION.value: RunStatus.RETRIEVING,
        WorkflowPhase.SOLUTION_PLANNING.value: RunStatus.PLANNING,
        WorkflowPhase.PLAN_REVIEW.value: RunStatus.PLANNING,
        WorkflowPhase.DOMAIN_VALIDATION.value: RunStatus.PLANNING,
        WorkflowPhase.WAITING_APPROVAL.value: RunStatus.WAITING_APPROVAL,
        WorkflowPhase.PREFLIGHT.value: RunStatus.WAITING_APPROVAL,
        WorkflowPhase.ACTION_EXECUTION.value: RunStatus.WAITING_APPROVAL,
        WorkflowPhase.VERIFICATION.value: RunStatus.VERIFYING,
        WorkflowPhase.RECOVERY.value: RunStatus.RECOVERY_REQUIRED,
    }
    target = mapping.get(phase)
    return None if target is None else target.value


__all__ = ["ResumeCheckpointMixin"]
