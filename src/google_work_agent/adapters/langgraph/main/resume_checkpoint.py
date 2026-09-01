"""Checkpoint projection and runtime verification for Application-owned Run resume."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor import SupervisorTarget
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowResumeRequest,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    CompiledAgentSubgraphIdV1,
    SemanticAgentOwnerIdV1,
)

if TYPE_CHECKING:
    from google_work_agent.adapters.langgraph.main.routing.route_after_supervisor import (
        GraphRouteTranslator,
    )
    from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
        ResumeTargetRegistry,
    )
    from google_work_agent.ports.system.checkpoint_port import CheckpointPort


class _ResumeCheckpointSuper(Protocol):
    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult: ...


class ResumeCheckpointMixin:
    """Expose persisted resume targets and continue only Handler-decided resumes."""

    _checkpoint_port: CheckpointPort

    if TYPE_CHECKING:
        _graph: Any
        _topology: tuple[str, ...]
        _route_translator: GraphRouteTranslator
        _resume_target_registry: ResumeTargetRegistry

        def _config_for_thread(self, workflow_key: str) -> dict[str, object]: ...

        def _is_profile_compatible(self, state: GraphState) -> bool: ...

        def _current_run_status(self, run_id: str) -> str: ...

        def _result_from_thread(
            self, *, workflow_key: str, run_id: str
        ) -> WorkflowInvocationResult: ...

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
            binding = self._checkpoint_port.load_workflow_binding(run_id)
            checkpoint = (
                None
                if binding is None
                else self._checkpoint_port.load_same_run_checkpoint(
                    run_id, binding.langgraph_thread_id
                )
            )
            if checkpoint is None or checkpoint.pre_reauth_status is None:
                return None
            authority: dict[str, object] = {"resume_status": checkpoint.pre_reauth_status.value}
            continuation_target = self._reauth_continuation_target(state)
            if continuation_target is not None:
                authority["continuation_target"] = continuation_target
            return authority
        if resume_kind == "RECOVERY_RECHECK":
            return {"resume_status": RunStatusV1.VERIFYING.value}
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
        return cast(_ResumeCheckpointSuper, super()).resume(request)

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
        if phase == WorkflowPhase.VERIFICATION.value:
            return "verification"
        if phase == WorkflowPhase.ACTION_EXECUTION.value:
            return None
        target_by_phase = {
            WorkflowPhase.TOOL_ROUTING.value: SupervisorTarget.TOOL_ROUTE,
            WorkflowPhase.CONTEXT_RETRIEVAL.value: SupervisorTarget.CONTEXT_RETRIEVAL,
            WorkflowPhase.WORK_ANALYSIS.value: SupervisorTarget.WORK_ANALYSIS,
            WorkflowPhase.SOLUTION_PLANNING.value: SupervisorTarget.SOLUTION_PLANNING,
            WorkflowPhase.PLAN_REVIEW.value: SupervisorTarget.PLAN_REVIEW_INSPECT,
            WorkflowPhase.DOMAIN_VALIDATION.value: SupervisorTarget.DOMAIN_VALIDATION,
            WorkflowPhase.WAITING_APPROVAL.value: SupervisorTarget.WAITING_APPROVAL,
            WorkflowPhase.PREFLIGHT.value: SupervisorTarget.PREFLIGHT,
        }
        target = target_by_phase.get(phase)
        if target is None:
            return None
        return self._route_translator.translate(target.value).node

    def resolve_pending_confirmation(self, run_id: str) -> dict[str, object] | None:
        binding = self._checkpoint_port.load_workflow_binding(run_id)
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
                target = _agent_resume_target(raw_target)
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


def _agent_resume_target(value: Mapping[object, object]) -> AgentNodeResumeTargetV2:
    return AgentNodeResumeTargetV2(
        kind=cast(Literal["AGENT_NODE"], _required_target_string(value, "kind")),
        semantic_owner_id=cast(
            SemanticAgentOwnerIdV1,
            _required_target_string(value, "semantic_owner_id"),
        ),
        compiled_subgraph_id=cast(
            CompiledAgentSubgraphIdV1,
            _required_target_string(value, "compiled_subgraph_id"),
        ),
        node_id=_required_target_string(value, "node_id"),
        graph_profile=cast(
            GraphProfileIdV1,
            _required_target_string(value, "graph_profile"),
        ),
        graph_version=_required_target_string(value, "graph_version"),
    )


def _required_target_string(value: Mapping[object, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"resume target {field} is invalid")
    return item


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


__all__ = ["ResumeCheckpointMixin"]
