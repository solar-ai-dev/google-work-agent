"""Canonical confirmation interrupt/resume behavior for the LangGraph runtime.

This module deliberately subclasses the large legacy runtime instead of
rewriting it. It replaces only the confirmation boundary that owns:

* durable interrupt metadata projection,
* interrupt-id/owner/resume-target validation,
* the explicit Domain ``ResumeConfirmation`` transition, and
* same-owner graph re-entry with a bounded, one-shot ``ConfirmationResponseV1``.
"""

from __future__ import annotations

from collections.abc import Mapping
from json import dumps
from typing import Any, Protocol, cast

from langgraph.types import interrupt

from google_work_agent.adapters.langgraph.confirmation_llm_runtime import (
    ConfirmationAwareLLMRuntime,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.route_translation import (
    confirmation_owner,
    confirmation_resume_status,
)
from google_work_agent.adapters.langgraph.runtime import (
    LangGraphWorkflowRuntime as _LegacyLangGraphWorkflowRuntime,
)
from google_work_agent.application.observability import sanitize_event_attributes
from google_work_agent.application.workflows import (
    GraphStateUpdateV1,
    SupervisorDecisionV1,
    SupervisorTarget,
    WorkflowPhase,
)
from google_work_agent.application.workflows.contracts import (
    ConfirmationResponseV1,
    PolicyConfirmationReceiptV1,
    validate_confirmation_response_v1,
)
from google_work_agent.application.workflows.handoff_contracts import (
    RegisteredResumeTargetRefV1,
)
from google_work_agent.domain import RunStatus
from google_work_agent.ports import AuditEventRecord


class _ConfirmationRunRepository(Protocol):
    """Narrow repository surface required by the canonical confirmation controller."""

    def get_by_id(self, run_id: str) -> Any: ...

    def resume_confirmation(
        self,
        run_id: str,
        *,
        expected_version: int,
        resume_status: RunStatus,
        finished_at_ms: int | None = None,
    ) -> Any: ...


_OWNER_WORKFLOW_PHASE = {
    "REQUEST_UNDERSTANDING": WorkflowPhase.REQUEST_ANALYSIS.value,
    "TOOL_ROUTE": WorkflowPhase.TOOL_ROUTING.value,
    "RETRIEVAL": WorkflowPhase.CONTEXT_RETRIEVAL.value,
    "WORK_ANALYSIS": WorkflowPhase.WORK_ANALYSIS.value,
    "PLANNING": WorkflowPhase.SOLUTION_PLANNING.value,
    "REVIEW": WorkflowPhase.PLAN_REVIEW.value,
}


class LangGraphWorkflowRuntime(_LegacyLangGraphWorkflowRuntime):
    """Legacy runtime with the canonical same-owner confirmation boundary."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        llm_runtime = kwargs.get("llm_runtime")
        if llm_runtime is None:
            raise TypeError("llm_runtime is required")
        confirmation_llm_runtime = ConfirmationAwareLLMRuntime(llm_runtime)
        kwargs["llm_runtime"] = confirmation_llm_runtime
        self._confirmation_llm_runtime = confirmation_llm_runtime
        super().__init__(*args, **kwargs)

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        merged = super()._merge_decision(state, update, decision)
        if decision["target"] == SupervisorTarget.WAITING_CONFIRMATION.value:
            return self._materialize_confirmation_interrupt(merged)
        return self._clear_consumed_confirmation(state=state, merged=merged)

    def _materialize_confirmation_interrupt(self, merged: GraphState) -> GraphState:
        raw_interrupt = merged.get("user_interrupt")
        if not isinstance(raw_interrupt, Mapping):
            raise ValueError("confirmation route requires a user_interrupt projection")
        origin_target = raw_interrupt.get("origin_target")
        if not isinstance(origin_target, str) or not origin_target:
            raise ValueError("confirmation interrupt is missing origin_target")

        owner_subgraph = confirmation_owner(origin_target)
        resume_target = self._resume_target_registry.issue(
            subgraph_id=owner_subgraph,
            node_id="finalize",
        )
        interrupt_id = self._id_factory()

        run_id = merged.get("run_id")
        if isinstance(run_id, str):
            self._confirmation_llm_runtime.clear(run_id=run_id)

        merged["user_interrupt"] = {
            **cast(dict[str, object], raw_interrupt),
            "interrupt_id": interrupt_id,
        }
        merged["prompt_context"] = {
            **cast(dict[str, object], merged.get("prompt_context", {})),
            "confirmation_interrupt": {
                "schema_version": 1,
                "interrupt_id": interrupt_id,
                "owner_subgraph": owner_subgraph,
                "origin_target": origin_target,
                "resume_target": dict(resume_target),
                "resume_status": confirmation_resume_status(owner_subgraph).value,
            },
        }
        cast(dict[str, object], merged["prompt_context"]).pop("confirmation_response", None)
        return merged

    def _clear_consumed_confirmation(self, *, state: GraphState, merged: GraphState) -> GraphState:
        """Expire the answer on the first non-confirmation disposition after resume."""
        prompt_context = state.get("prompt_context")
        if not isinstance(prompt_context, Mapping) or "confirmation_response" not in prompt_context:
            return merged
        run_id = state.get("run_id")
        if isinstance(run_id, str):
            self._confirmation_llm_runtime.clear(run_id=run_id)
        next_prompt_context = dict(cast(Mapping[str, object], merged.get("prompt_context", {})))
        next_prompt_context.pop("confirmation_response", None)
        next_prompt_context.pop("confirmation_interrupt", None)
        merged["prompt_context"] = next_prompt_context
        return merged

    def _waiting_confirmation_node(self, state: GraphState) -> GraphState:
        """Shared Main-Graph interrupt boundary for the 5 non-Request-Understanding
        owners (Tool Route/Retrieval/Work Analysis/Planning/Review). Request
        Understanding no longer routes here -- see
        ``_confirm_request_understanding_inline`` for its own-subgraph interrupt."""
        request = self._request_from_state(state)
        prompt_context = cast(dict[str, object], state.get("prompt_context", {}))
        raw_meta = prompt_context.get("confirmation_interrupt")
        if not isinstance(raw_meta, Mapping):
            raise ValueError("confirmation checkpoint metadata is missing")

        interrupt_id = self._required_string(raw_meta.get("interrupt_id"), "interrupt_id")
        owner_subgraph = self._required_string(
            raw_meta.get("owner_subgraph"), "owner_subgraph"
        )
        expected_origin_target = self._required_string(
            raw_meta.get("origin_target"), "origin_target"
        )
        raw_resume_target = raw_meta.get("resume_target")
        if not isinstance(raw_resume_target, Mapping):
            raise ValueError("confirmation resume_target is missing")
        resume_target = cast(RegisteredResumeTargetRefV1, dict(raw_resume_target))
        resume_node = self._resume_target_registry.resolve(resume_target)

        raw_interrupt = state.get("user_interrupt")
        if not isinstance(raw_interrupt, Mapping):
            raise ValueError("confirmation user_interrupt is missing")
        if raw_interrupt.get("origin_target") != expected_origin_target:
            raise ValueError("confirmation origin target does not match checkpoint metadata")
        if raw_interrupt.get("interrupt_id") != interrupt_id:
            raise ValueError("confirmation interrupt id does not match checkpoint metadata")

        confirmation_response, early_return_patch = self._run_confirmation_interrupt_cycle(
            request=request,
            interrupt_id=interrupt_id,
            owner_subgraph=owner_subgraph,
            raw_interrupt=raw_interrupt,
            raw_stored_resume_status=raw_meta.get("resume_status"),
            check_stored_resume_status=True,
        )
        if early_return_patch is not None:
            return cast(GraphState, {**state, **early_return_patch})
        assert confirmation_response is not None

        self._confirmation_llm_runtime.register(
            run_id=request.run_id,
            origin_target=expected_origin_target,
            response=confirmation_response,
        )

        return {
            **state,
            "__target__": resume_node,
            "__logical_target__": resume_node,
            "user_interrupt": None,
            "workflow_phase": _OWNER_WORKFLOW_PHASE[owner_subgraph],
            "prompt_context": {
                **prompt_context,
                "confirmation_response": dict(confirmation_response),
            },
        }

    def _confirm_request_understanding_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Request Understanding's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="REQUEST_UNDERSTANDING")

    def _confirm_context_retrieval_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Retrieval's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="RETRIEVAL")

    def _confirm_tool_route_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Tool Route's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="TOOL_ROUTE")

    def _confirm_work_analysis_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Work Analysis's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="WORK_ANALYSIS")

    def _confirm_planning_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Planning's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="PLANNING")

    def _confirm_review_inline(
        self, state: GraphState
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Review's own nested-checkpoint interrupt entry point."""
        return self._confirm_owner_inline(state, owner_subgraph="REVIEW")

    def _record_policy_confirmation_receipt(
        self, run_id: str, receipt: PolicyConfirmationReceiptV1
    ) -> None:
        """Persist the doc-mandated ``POLICY_CONFIRMATION_RECORDED`` audit row
        (11-observability-logging-audit.md SS6) for one SCOPE_EXPANSION /
        DUPLICATE_OVERRIDE / CONFLICT_OVERRIDE Receipt. Allowlisted metadata
        only -- confirmation_receipt_id, interrupt_id, confirmation_kind,
        decision, decision_context_hash, and the affected route/resource ids
        -- never the raw question/response text. Shares
        confirmation_receipt_id and decision_context_hash with the LangGraph
        Checkpoint's ``PolicyConfirmationReceiptV1`` so an Approval Snapshot
        can reference this row later.
        """
        metadata = sanitize_event_attributes(
            {
                "confirmation_receipt_id": receipt["confirmation_receipt_id"],
                "interrupt_id": receipt["interrupt_id"],
                "confirmation_kind": receipt["confirmation_kind"],
                "decision": receipt["decision"],
                "decision_context_hash": receipt["decision_context_hash"],
                "affected_route_ids": list(receipt["affected_route_ids"]),
                "affected_resource_refs": list(receipt["affected_resource_refs"]),
            }
        ).values
        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.audits.add(
                AuditEventRecord(
                    account_id=None,
                    run_id=run_id,
                    action_id=None,
                    actor_type="AGENT",
                    actor_id="confirmation_controller",
                    actor_display="Confirmation Controller",
                    event_type="POLICY_CONFIRMATION_RECORDED",
                    outcome=receipt["decision"],
                    metadata_json=dumps(metadata, sort_keys=True),
                    created_at_ms=self._now_ms(),
                )
            )
            unit_of_work.commit()

    def _confirm_owner_inline(
        self, state: GraphState, *, owner_subgraph: str
    ) -> tuple[ConfirmationResponseV1 | None, dict[str, object] | None]:
        """Generic same-owner nested-checkpoint interrupt entry point.

        Called from within an owner's OWN finalize node -- i.e. from a node
        that is itself part of that owner's compiled nested subgraph -- so
        ``interrupt()`` below is attributed to that nested task and resumes
        there natively, without a round trip through the shared Main-Graph
        ``waiting_confirmation`` node. ``state["user_interrupt"]`` must
        already carry the bounded interrupt payload (including
        ``interrupt_id``); the owner's own upstream, never-replayed node (or
        a freshly self-looped finalize invocation for a later round) builds
        it once, before any pause, so it survives finalize's node-replay on
        resume unchanged.
        """
        request = self._request_from_state(state)
        raw_interrupt = state.get("user_interrupt")
        if not isinstance(raw_interrupt, Mapping):
            raise ValueError("confirmation user_interrupt is missing")
        interrupt_id = self._required_string(raw_interrupt.get("interrupt_id"), "interrupt_id")
        return self._run_confirmation_interrupt_cycle(
            request=request,
            interrupt_id=interrupt_id,
            owner_subgraph=owner_subgraph,
            raw_interrupt=raw_interrupt,
            raw_stored_resume_status=None,
            check_stored_resume_status=False,
        )

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
        """Shared core: guarded ``RequestConfirmation``, the actual
        ``interrupt()`` call, response validation, and ``ResumeConfirmation``.

        Returns ``(confirmation_response, None)`` on success, or
        ``(None, state_patch)`` when the caller must return
        ``{**state, **state_patch}`` immediately (not-applied/conflict).
        Callers own everything after a successful response: the shared
        ``waiting_confirmation`` node routes back to the owner's Main-Graph
        node, while Request Understanding's inline caller continues within
        the same nested subgraph invocation instead.
        """
        current_status = RunStatus(self._current_run_status(request.run_id))
        if current_status is not RunStatus.WAITING_CONFIRMATION:
            self._transition_run(request.run_id, "request_confirmation")
        current_status = RunStatus(self._current_run_status(request.run_id))
        if current_status is not RunStatus.WAITING_CONFIRMATION:
            return None, {
                "__target__": "end",
                "execution_summary": {"result": "REQUEST_CONFIRMATION_NOT_APPLIED"},
            }

        raw_resume = interrupt(
            {
                "interrupt_kind": "CONFIRMATION",
                "run_id": request.run_id,
                **dict(raw_interrupt),
            }
        )
        if not isinstance(raw_resume, Mapping):
            raise ValueError("confirmation resume payload must be an object")
        if raw_resume.get("interrupt_id") != interrupt_id:
            raise ValueError("confirmation response interrupt_id mismatch")

        confirmation_response = validate_confirmation_response_v1(
            {
                "schema_version": raw_resume.get("schema_version"),
                "response_kind": raw_resume.get("response_kind"),
                "selected_option_ids": raw_resume.get("selected_option_ids"),
                "free_text": raw_resume.get("free_text"),
            }
        )
        self._validate_confirmation_option_scope(
            interrupt_payload=raw_interrupt,
            response=confirmation_response,
        )

        expected_resume_status = confirmation_resume_status(owner_subgraph)
        if (
            check_stored_resume_status
            and raw_stored_resume_status != expected_resume_status.value
        ):
            raise ValueError("confirmation resume status metadata is invalid")

        with self._unit_of_work_factory() as unit_of_work:
            repository = cast(_ConfirmationRunRepository, unit_of_work.runs)
            run = repository.get_by_id(request.run_id)
            if run is None:
                raise LookupError(f"run not found: {request.run_id}")
            transition = repository.resume_confirmation(
                request.run_id,
                expected_version=run.version,
                resume_status=expected_resume_status,
                finished_at_ms=None,
            )
            if not transition.applied:
                return None, {
                    "__target__": "end",
                    "execution_summary": {
                        "result": "CONFIRMATION_RESUME_CONFLICT",
                        "result_code": transition.result_code.value,
                    },
                }
            unit_of_work.commit()

        return confirmation_response, None

    @staticmethod
    def _validate_confirmation_option_scope(
        *,
        interrupt_payload: Mapping[str, object],
        response: ConfirmationResponseV1,
    ) -> None:
        """Bind OPTION_SELECTION to the exact options exposed by this interrupt."""
        raw_options = interrupt_payload.get("options", [])
        if not isinstance(raw_options, list):
            raise ValueError("confirmation options must be a list")
        allowed_ids: set[str] = set()
        for option in raw_options:
            if not isinstance(option, Mapping):
                raise ValueError("confirmation option must be an object")
            option_id = option.get("option_id")
            if not isinstance(option_id, str) or not option_id:
                raise ValueError("confirmation option_id is invalid")
            allowed_ids.add(option_id)

        if response["response_kind"] == "OPTION_SELECTION":
            if not allowed_ids:
                raise ValueError("free-text confirmation does not accept option selection")
            unknown = set(response["selected_option_ids"]) - allowed_ids
            if unknown:
                raise ValueError(
                    "confirmation selected_option_ids are outside the interrupt options"
                )
        elif allowed_ids:
            raise ValueError("closed-choice confirmation requires OPTION_SELECTION")


__all__ = ["LangGraphWorkflowRuntime"]
