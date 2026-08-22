"""Checkpoint projection and runtime verification for Application-owned Run resume."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.canonical_freshness_runtime import (
    LangGraphWorkflowRuntime as _CanonicalFreshnessRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.route_translation import (
    confirmation_owner,
    confirmation_resume_status,
)
from google_work_agent.application.workflows.contracts import (
    ConfirmationResponseV1,
    WorkflowPhase,
    validate_confirmation_response_v1,
)
from google_work_agent.application.workflows.supervisor import SupervisorTarget
from google_work_agent.domain import RunStatus
from google_work_agent.ports import WorkflowInvocationResult, WorkflowOutcome, WorkflowResumeRequest


class LangGraphWorkflowRuntime(_CanonicalFreshnessRuntime):
    """Expose persisted resume targets and continue only Handler-decided resumes."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._handler_confirmation_resumes: set[str] = set()

    def resolve_resume_authority(self, *, run_id: str, workflow_key: str, resume_kind: str) -> dict[str, object] | None:
        """Read checkpoint authority without mutating Domain or workflow state."""
        snapshot = self._graph.get_state(self._config_for_thread(workflow_key))
        if not snapshot.values and not snapshot.next:
            return None
        state = cast(GraphState, snapshot.values)
        if resume_kind == "CONFIRMATION":
            prompt_context = state.get("prompt_context")
            if isinstance(prompt_context, Mapping):
                meta = prompt_context.get("confirmation_interrupt")
                if isinstance(meta, Mapping):
                    stored = meta.get("resume_status")
                    interrupt_id = meta.get("interrupt_id")
                    if isinstance(stored, str) and isinstance(interrupt_id, str):
                        try:
                            return {"resume_status": RunStatus(stored).value, "interrupt_id": interrupt_id}
                        except ValueError:
                            return None
            for task in snapshot.tasks:
                for pending in getattr(task, "interrupts", ()):
                    value = getattr(pending, "value", None)
                    if not isinstance(value, Mapping) or value.get("interrupt_kind") != "CONFIRMATION":
                        continue
                    origin_target = value.get("origin_target")
                    interrupt_id = value.get("interrupt_id")
                    if isinstance(origin_target, str) and origin_target and isinstance(interrupt_id, str):
                        return {
                            "resume_status": confirmation_resume_status(confirmation_owner(origin_target)).value,
                            "interrupt_id": interrupt_id,
                        }
            return None
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

    def resolve_resume_domain_status(self, *, run_id: str, workflow_key: str, resume_kind: str) -> str | None:
        authority = self.resolve_resume_authority(run_id=run_id, workflow_key=workflow_key, resume_kind=resume_kind)
        status = None if authority is None else authority.get("resume_status")
        return status if isinstance(status, str) else None

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        if request.resume_kind == "CONFIRMATION":
            self._handler_confirmation_resumes.add(request.run_id)
            try:
                return super().resume(request)
            finally:
                self._handler_confirmation_resumes.discard(request.run_id)
        if request.resume_kind == "REAUTH_COMPLETED":
            return self._resume_after_reauth_transition(request)
        return super().resume(request)

    def _resume_after_reauth_transition(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        """Validate the persisted target and continue it without recovery semantics."""
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(request.run_id, request.workflow_key, WorkflowOutcome.CHECKPOINT_MISSING, {})
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
        expected_target = None if authority is None else authority.get("continuation_target")
        requested_target = request.resume_payload.get("continuation_target")
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

    def _run_confirmation_interrupt_cycle(
        self,
        *,
        request: Any,
        interrupt_id: str,
        owner_subgraph: str,
        raw_interrupt: Mapping[str, object],
        raw_stored_resume_status: object,
        check_stored_resume_status: bool,
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Request confirmation initially; on resume verify Handler-restored Domain truth."""
        expected_resume_status = confirmation_resume_status(owner_subgraph)
        pretransitioned = request.run_id in self._handler_confirmation_resumes
        current_status = RunStatus(self._current_run_status(request.run_id))
        if pretransitioned:
            if current_status is not expected_resume_status:
                return None, {
                    "__target__": "end",
                    "execution_summary": {"result": "CONFIRMATION_RESUME_CONFLICT"},
                }
        else:
            if current_status is not RunStatus.WAITING_CONFIRMATION:
                self._transition_run(request.run_id, "request_confirmation")
            if RunStatus(self._current_run_status(request.run_id)) is not RunStatus.WAITING_CONFIRMATION:
                return None, {
                    "__target__": "end",
                    "execution_summary": {"result": "REQUEST_CONFIRMATION_NOT_APPLIED"},
                }

        raw_resume = interrupt({
            "interrupt_kind": "CONFIRMATION",
            "run_id": request.run_id,
            **dict(raw_interrupt),
        })
        if not isinstance(raw_resume, Mapping):
            raise ValueError("confirmation resume payload must be an object")
        if raw_resume.get("interrupt_id") != interrupt_id:
            raise ValueError("confirmation response interrupt_id mismatch")
        confirmation_response = validate_confirmation_response_v1({
            "schema_version": raw_resume.get("schema_version"),
            "response_kind": raw_resume.get("response_kind"),
            "selected_option_ids": raw_resume.get("selected_option_ids"),
            "free_text": raw_resume.get("free_text"),
        })
        self._validate_confirmation_option_scope(
            interrupt_payload=raw_interrupt,
            response=confirmation_response,
        )
        if check_stored_resume_status and raw_stored_resume_status != expected_resume_status.value:
            raise ValueError("confirmation resume status metadata is invalid")
        if not pretransitioned:
            return None, {
                "__target__": "end",
                "execution_summary": {"result": "CONFIRMATION_RESUME_REQUIRES_APPLICATION_TRANSITION"},
            }
        return confirmation_response, None


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


__all__ = ["LangGraphWorkflowRuntime"]
