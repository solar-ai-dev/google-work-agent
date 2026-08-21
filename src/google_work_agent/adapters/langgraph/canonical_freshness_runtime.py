"""Canonical downstream-artifact freshness compatibility boundary.

Until Main State V2 moves every downstream artifact onto ``meta.based_on``
freshness, the legacy Supervisor still clears downstream fields explicitly on
route reconsideration. It omitted the canonical ``retrieval_result`` field,
leaving an old RetrievalResult alive while Tool Route was being recomputed.

This release wrapper fixes only that omission. It also closes write-runtime
compatibility seams without changing Main State/Supervisor authority: durable
cancel checks use the command-receipt repository, recovery completion returns
its CommandResult-backed response, terminal cancellation explicitly discards
run-scoped transient stores, and corrective-plan recovery resumes through the
registered production Planning route.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.canonical_response_runtime import (
    LangGraphWorkflowRuntime as _CanonicalResponseRuntime,
)
from google_work_agent.adapters.langgraph.corrective_plan_persistence import (
    persist_reserved_corrective_write_plan,
)
from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.application.cancel_intent import (
    CancelIntentReceiptReader,
    has_durable_cancel_intent,
)
from google_work_agent.application.run_terminal import (
    CompleteWriteRunCommand,
    RunTransitionResponse,
)
from google_work_agent.application.workflows import (
    GraphStateUpdateV1,
    SupervisorDecisionV1,
    SupervisorTarget,
    WorkflowPhase,
)
from google_work_agent.application.workflows.handoff_contracts import ActionPlanDraftV1
from google_work_agent.domain import ActionStatus, RunStatus
from google_work_agent.ports import (
    PlanStatus,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowResumeRequest,
)


class LangGraphWorkflowRuntime(_CanonicalResponseRuntime):
    """Release runtime with canonical freshness and write safety seams."""

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        merged = super()._merge_decision(state, update, decision)
        if _is_route_reconsideration_to_tool_route(merged):
            return {**merged, "retrieval_result": None}
        return merged

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        """Resume registered application continuations or ordinary workflow pauses."""
        if request.resume_kind != "RECOVERY_CORRECTIVE_PLAN":
            return super().resume(request)
        return self._resume_corrective_plan(request)

    def _resume_corrective_plan(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        """Continue CREATE_CORRECTIVE_PLAN through the profile's Planning node.

        The resume target is never supplied by the API or LLM. Domain has
        already created the next DRAFT Plan and moved the Run to PLANNING;
        this boundary validates those durable facts, translates the single
        canonical PLANNING target through the compiled profile registry, then
        advances from the graph's existing recovery node.
        """
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if not snapshot.values and not snapshot.next:
            return WorkflowInvocationResult(
                run_id=request.run_id,
                workflow_key=request.workflow_key,
                outcome=WorkflowOutcome.CHECKPOINT_MISSING,
                payload={},
            )
        state = cast(GraphState, snapshot.values)
        if not self._is_profile_compatible(state):
            return self._corrective_resume_conflict(
                request,
                reason="graph profile does not match the persisted checkpoint",
            )
        if snapshot.next:
            return self._corrective_resume_conflict(
                request,
                reason="corrective-plan recovery cannot bypass a pending interrupt",
            )

        plan_id = request.resume_payload.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            return self._corrective_resume_conflict(
                request,
                reason="corrective-plan resume requires the server-created plan_id",
            )

        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get_by_id(request.run_id)
            plan = unit_of_work.plans.get_by_id(plan_id)
            plans = unit_of_work.plans.list_by_run(request.run_id)
        latest_plan = max(plans, key=lambda item: item.revision_no) if plans else None
        if (
            run is None
            or run.status is not RunStatus.PLANNING
            or plan is None
            or plan.run_id != request.run_id
            or plan.status is not PlanStatus.DRAFT
            or latest_plan is None
            or latest_plan.id != plan.id
        ):
            return self._corrective_resume_conflict(
                request,
                reason="Domain does not expose the requested latest DRAFT corrective plan",
            )

        translation = self._route_translator.translate(SupervisorTarget.PLANNING.value)
        self._graph.update_state(
            config,
            {
                # Corrective recovery owns a reserved *destination* Plan. Do
                # not overload the ordinary replan source marker: its legacy
                # meaning includes allocating a new revision and remapping
                # children. The destination marker is consumed exactly once
                # after successful persistence.
                "__replan_from_plan_id__": None,
                "__reserved_corrective_plan_id__": plan.id,
                "__logical_target__": SupervisorTarget.PLANNING.value,
                "__target__": translation.node,
                "workflow_phase": WorkflowPhase.SOLUTION_PLANNING.value,
                "plan_draft": None,
                "plan_review": None,
                "approved_plan_id": None,
                "execution_summary": None,
                "verification_summary": None,
                "finalize_intent": None,
            },
            as_node="recovery",
        )
        self._graph.invoke(None, config=config)
        return self._result_from_thread(
            workflow_key=request.workflow_key,
            run_id=request.run_id,
        )

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str:
        """Persist ordinary replans normally, or fill one reserved corrective revision."""
        reserved_plan_id = state.get("__reserved_corrective_plan_id__")
        if not isinstance(reserved_plan_id, str) or not reserved_plan_id:
            return super()._persist_write_plan(state, plan_draft)

        with self._unit_of_work_factory() as unit_of_work:
            reserved_plan = unit_of_work.plans.get_by_id(reserved_plan_id)
        if reserved_plan is None:
            raise LookupError(f"reserved corrective plan not found: {reserved_plan_id}")

        persisted_plan_id = persist_reserved_corrective_write_plan(
            self,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )
        # One-shot marker: only consume after Save + Publish both succeeded.
        # If persistence raises, the marker remains durable for fail-closed
        # recovery rather than silently losing the reserved destination.
        state["__reserved_corrective_plan_id__"] = None
        return persisted_plan_id

    @staticmethod
    def _corrective_resume_conflict(
        request: WorkflowResumeRequest,
        *,
        reason: str,
    ) -> WorkflowInvocationResult:
        return WorkflowInvocationResult(
            run_id=request.run_id,
            workflow_key=request.workflow_key,
            outcome=WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
            payload={"reason": reason},
        )

    def _has_persisted_cancel_intent(self, run_id: str) -> bool:
        """Production cancel authority: APPLIED RequestCancel command receipt."""
        with self._unit_of_work_factory() as unit_of_work:
            reader = cast(CancelIntentReceiptReader, unit_of_work.command_receipts)
            return has_durable_cancel_intent(reader, run_id)

    def _complete_write_run_if_verified(
        self,
        plan_id: str,
        run_id: str,
    ) -> RunTransitionResponse | None:
        """Return completion outcome instead of swallowing applied=false facts."""
        if self._has_persisted_cancel_intent(run_id):
            return None
        actions = self._list_actions(plan_id)
        if not actions or not all(
            action.status == ActionStatus.VERIFIED.value for action in actions
        ):
            return None
        return self._complete_write_run(
            CompleteWriteRunCommand(
                command_id=self._id_factory(),
                request_hash=self._request_hash(
                    {"kind": "complete_recovered_write_run", "run_id": run_id}
                ),
                run_id=run_id,
                expected_version=self._current_run_version(run_id),
            )
        )

    def discard_run_transients(self, run_id: str) -> None:
        """Release every memory-only transient owned by a terminal Run."""
        self._evidence_store.discard_run(run_id=run_id)
        self._read_result_cache.discard_run(run_id=run_id)
        self._llm_runtime.discard_run(run_id=run_id)


def _is_route_reconsideration_to_tool_route(state: GraphState) -> bool:
    if state.get("__logical_target__") != SupervisorTarget.TOOL_ROUTE.value:
        return False
    signal = state.get("workflow_signal")
    return isinstance(signal, Mapping) and signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"


__all__ = ["LangGraphWorkflowRuntime"]
