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

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from google_work_agent.adapters.langgraph.corrective_plan_reachability import (
    CorrectivePlanContinuationRequired,
    persist_reachable_corrective_write_plan,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorDecisionV1,
    SupervisorTarget,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    ActionPlanDraftV1,
)
from google_work_agent.application.use_cases.plan.persistence_projection import (
    current_plan_tuple,
    load_plan_record,
)
from google_work_agent.application.use_cases.run.cancel_intent import has_durable_cancel_intent
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowRecoveryRequest,
    WorkflowResumeRequest,
)

if TYPE_CHECKING:
    from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class _ArtifactFreshnessSuper(Protocol):
    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState: ...

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult: ...

    def recover_open_run(self, request: WorkflowRecoveryRequest) -> WorkflowInvocationResult: ...

    def _persist_write_plan(self, state: GraphState, plan_draft: ActionPlanDraftV1) -> str: ...


class ArtifactFreshnessMixin:
    """Release runtime with canonical freshness and write safety seams."""

    if TYPE_CHECKING:
        _graph: Any
        _route_translator: Any
        _unit_of_work_factory: Callable[[], UnitOfWork]

        def _list_actions(self, plan_id: str) -> tuple[Any, ...]: ...

        _evidence_store: Any
        _read_result_cache: Any
        _llm_runtime: Any

        def _config_for_thread(self, workflow_key: str) -> dict[str, Any]: ...

        def _result_from_thread(
            self, *, workflow_key: str, run_id: str
        ) -> WorkflowInvocationResult: ...

        def _is_profile_compatible(self, state: GraphState) -> bool: ...

    def _merge_decision(
        self,
        state: GraphState,
        update: GraphStateUpdateV1,
        decision: SupervisorDecisionV1,
    ) -> GraphState:
        merged = cast(_ArtifactFreshnessSuper, super())._merge_decision(state, update, decision)
        if _is_route_reconsideration_to_tool_route(merged):
            merged["retrieval_result"] = None
        return merged

    def resume(self, request: WorkflowResumeRequest) -> WorkflowInvocationResult:
        """Resume registered application continuations or ordinary workflow pauses."""
        if request.resume_kind != "RECOVERY_CORRECTIVE_PLAN":
            return cast(_ArtifactFreshnessSuper, super()).resume(request)
        return self._resume_corrective_plan_safely(request)

    def recover_open_run(
        self,
        request: WorkflowRecoveryRequest,
    ) -> WorkflowInvocationResult:
        """Recover a checkpoint-owned corrective continuation before generic recovery.

        Startup recovery already enumerates every unfinished Run. A persisted
        corrective destination marker is sufficient to route PLANNING/DRAFT or
        stale WAITING_APPROVAL checkpoints back through the exact same
        registered corrective continuation. Marker-absent runs retain the
        existing generic open-run recovery semantics.
        """
        config = self._config_for_thread(request.workflow_key)
        snapshot = self._graph.get_state(config)
        if snapshot.values:
            state = cast(GraphState, snapshot.values)
            plan_id = state.get("__reserved_corrective_plan_id__")
            if (
                isinstance(plan_id, str)
                and plan_id
                and request.domain_status
                in {
                    RunStatusV1.PLANNING.value,
                    RunStatusV1.WAITING_APPROVAL.value,
                }
            ):
                return self._resume_corrective_plan_safely(
                    WorkflowResumeRequest(
                        run_id=request.run_id,
                        workflow_key=request.workflow_key,
                        resume_kind="RECOVERY_CORRECTIVE_PLAN",
                        resume_payload={"plan_id": plan_id},
                        correlation=request.correlation,
                    )
                )
        return cast(_ArtifactFreshnessSuper, super()).recover_open_run(request)

    def _resume_corrective_plan_safely(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        """Keep only a durably proven Save-only corrective boundary non-terminal."""
        try:
            return self._resume_corrective_plan(request)
        except CorrectivePlanContinuationRequired as continuation:
            plan_id = request.resume_payload.get("plan_id")
            if continuation.run_id != request.run_id or continuation.plan_id != plan_id:
                raise
            # No new workflow/domain status is invented. The Run remains
            # PLANNING and the failed LangGraph task + marker remain
            # checkpointed. Coordinator therefore receives the existing
            # ACCEPTED projection instead of generic exception -> FAILED.
            return self._result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )

    def _resume_corrective_plan(
        self,
        request: WorkflowResumeRequest,
    ) -> WorkflowInvocationResult:
        """Continue or replay CREATE_CORRECTIVE_PLAN without blind materialization.

        Domain owns the reserved revision. If a prior graph invocation failed
        after Save (or even after Publish committed), a retry may have a pending
        non-interrupt task. That task is resumed in place only when the
        checkpoint already carries this exact reserved destination marker.
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

        plan_id = request.resume_payload.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            return self._corrective_resume_conflict(
                request,
                reason="corrective-plan resume requires the server-created plan_id",
            )

        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.runs.get(request.run_id)
            plan = load_plan_record(unit_of_work.plans, plan_id)
            plans = current_plan_tuple(unit_of_work.plans, request.run_id)
        latest_plan = max(plans, key=lambda item: item.revision_no) if plans else None
        if (
            run is None
            or plan is None
            or plan.run_id != request.run_id
            or latest_plan is None
            or latest_plan.id != plan.id
        ):
            return self._corrective_resume_conflict(
                request,
                reason="Domain does not expose the requested latest corrective Plan",
            )

        # Idempotent replay after a prior Publish committed. The durable
        # Run/Plan pair is authoritative; no Planning node and no persistence
        # service is invoked again. If a stale checkpoint still carries the
        # one-shot destination marker, reconcile it to WAITING_APPROVAL.
        if (
            run.status is RunStatusV1.WAITING_APPROVAL
            and plan.status is PlanStatusV1.WAITING_APPROVAL
        ):
            if state.get("__reserved_corrective_plan_id__") == plan.id:
                translation = self._route_translator.translate(
                    SupervisorTarget.WAITING_APPROVAL.value
                )
                self._graph.update_state(
                    config,
                    {
                        "__reserved_corrective_plan_id__": None,
                        "approved_plan_id": plan.id,
                        "__logical_target__": SupervisorTarget.WAITING_APPROVAL.value,
                        "__target__": translation.node,
                        "workflow_phase": WorkflowPhase.WAITING_APPROVAL.value,
                    },
                    as_node="domain_validation",
                )
            return self._result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )

        if run.status is not RunStatusV1.PLANNING or plan.status is not PlanStatusV1.DRAFT:
            return self._corrective_resume_conflict(
                request,
                reason="corrective continuation requires PLANNING/DRAFT durable state",
            )

        has_pending_interrupt = any(
            bool(getattr(task, "interrupts", ())) for task in snapshot.tasks
        )
        if has_pending_interrupt:
            return self._corrective_resume_conflict(
                request,
                reason="corrective-plan recovery cannot bypass a pending interrupt",
            )

        # Retry a failed in-flight Planning/Domain Validation task in place.
        # This is the path that reaches materialized-DRAFT publish-only
        # continuation; do not write a second marker or restart Planning.
        if snapshot.next:
            if state.get("__reserved_corrective_plan_id__") != plan.id:
                return self._corrective_resume_conflict(
                    request,
                    reason="pending corrective task does not own the requested reserved Plan",
                )
            self._graph.invoke(None, config=config)
            return self._result_from_thread(
                workflow_key=request.workflow_key,
                run_id=request.run_id,
            )

        translation = self._route_translator.translate(SupervisorTarget.SOLUTION_PLANNING.value)
        self._graph.update_state(
            config,
            {
                "__replan_from_plan_id__": None,
                "__reserved_corrective_plan_id__": plan.id,
                "__logical_target__": SupervisorTarget.SOLUTION_PLANNING.value,
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
        """Persist ordinary replans normally, or continue one reserved corrective revision."""
        reserved_plan_id = state.get("__reserved_corrective_plan_id__")
        if not isinstance(reserved_plan_id, str) or not reserved_plan_id:
            return cast(_ArtifactFreshnessSuper, super())._persist_write_plan(state, plan_draft)

        with self._unit_of_work_factory() as unit_of_work:
            reserved_plan = load_plan_record(unit_of_work.plans, reserved_plan_id)
        if reserved_plan is None:
            raise LookupError(f"reserved corrective plan not found: {reserved_plan_id}")

        persisted_plan_id = persist_reachable_corrective_write_plan(
            self,
            state=state,
            plan_draft=plan_draft,
            reserved_plan=reserved_plan,
        )
        # One-shot marker is consumed only after the helper has reached either
        # a verified Publish success or a verified already-published replay.
        # Save-only failure and candidate drift leave it intact for retry.
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
            reader = unit_of_work.command_receipts
            return has_durable_cancel_intent(reader, run_id)

    def _write_run_completion_ready(
        self,
        plan_id: str,
        run_id: str,
    ) -> bool:
        """Read-only readiness projection consumed by TERMINAL_COMMIT."""
        if self._has_persisted_cancel_intent(run_id):
            return False
        actions = self._list_actions(plan_id)
        return bool(actions) and all(
            action.status == ActionStatusV1.VERIFIED.value for action in actions
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


__all__ = ["ArtifactFreshnessMixin"]
