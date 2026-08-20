"""Canonical downstream-artifact freshness compatibility boundary.

Until Main State V2 moves every downstream artifact onto ``meta.based_on``
freshness, the legacy Supervisor still clears downstream fields explicitly on
route reconsideration. It omitted the canonical ``retrieval_result`` field,
leaving an old RetrievalResult alive while Tool Route was being recomputed.

This release wrapper fixes only that omission. It also closes write-runtime
compatibility seams without changing Main State/Supervisor authority: durable
cancel checks use the command-receipt repository, recovery completion returns
its CommandResult-backed response, and terminal cancellation can explicitly
discard run-scoped transient stores.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.canonical_response_runtime import (
    LangGraphWorkflowRuntime as _CanonicalResponseRuntime,
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
)
from google_work_agent.domain import ActionStatus


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
        """Terminal-lifecycle hook for Integration-owned cancellation cleanup.

        This only delegates to existing run-scoped stores; it does not alter
        Retrieval data architecture or Main State. Integration must call it
        after durable cancellation reaches CANCELLED.
        """
        self._evidence_store.discard_run(run_id=run_id)
        self._read_result_cache.discard_run(run_id=run_id)
        self._llm_runtime.discard_run(run_id=run_id)


def _is_route_reconsideration_to_tool_route(state: GraphState) -> bool:
    if state.get("__logical_target__") != SupervisorTarget.TOOL_ROUTE.value:
        return False
    signal = state.get("workflow_signal")
    return isinstance(signal, Mapping) and signal.get("kind") == "ROUTE_RECONSIDERATION_REQUIRED"


__all__ = ["LangGraphWorkflowRuntime"]
